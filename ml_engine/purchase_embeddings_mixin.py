"""
ml_engine/purchase_embeddings_mixin.py
──────────────────────────────────────────────────────────────────────────────
Purchase2Vec — Partner Sequence Embeddings
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Learns a 32-dimensional embedding per partner from their raw product purchase
sequences (concept: Amazon's Item2Vec / Word2Vec on purchase logs).

Why this matters:
  Two partners with identical total spend can have entirely different buying
  patterns. Partner A buys [Fan → Fan → Fan → AC] every month (volume buyer).
  Partner B buys [Fan → AC → Fridge → TV] (diversified explorer). Aggregated
  features treat them the same. Embeddings distinguish them.

Integration:
  Called from clustering_mixin._compress_features_weighted_pca_umap()
  Adds an 'embed' feature group (weight 0.10) to the PCA/UMAP input matrix.

Fallback behavior:
  - If gensim is not installed → embeddings silently disabled
  - If a partner has < 3 purchases → assigned zero vector (no crash)
  - If sequences load fails → embeddings disabled, clustering continues

Config (via .env):
  ENABLE_PURCHASE_EMBEDDINGS=true   # set to false to disable for speed
  EMBEDDING_VECTOR_SIZE=32          # dimensions per partner embedding
  EMBEDDING_LOOKBACK_DAYS=365       # how far back to load transactions
"""

import logging
import numpy as np
import pandas as pd
from sqlalchemy import text

logger = logging.getLogger(__name__)


class PurchaseEmbeddingsMixin:
    """
    Mixin that adds purchase sequence embedding capabilities to the engine.
    Inherit alongside ClusteringMixin so the embedding matrix is available
    during the clustering feature-building step.
    """

    # Instance-level state (reset each time ensure_purchase_embeddings is called)
    _purchase_sequences: dict = {}
    _word2vec_model = None
    _partner_embedding_matrix: "pd.DataFrame | None" = None

    # ── Public entry point ────────────────────────────────────────────────────
    def ensure_purchase_embeddings(self) -> pd.DataFrame:
        """
        Load sequences → train Word2Vec → compute partner embeddings.
        Returns a DataFrame with shape (n_partners, vector_size) indexed by company_name.
        Cached for the lifetime of this engine instance (reset at next clustering run).
        """
        if not self._embeddings_enabled():
            return pd.DataFrame()

        if (
            self._partner_embedding_matrix is not None
            and not self._partner_embedding_matrix.empty
        ):
            return self._partner_embedding_matrix

        sequences = self._load_purchase_sequences()
        if not sequences:
            self._partner_embedding_matrix = pd.DataFrame()
            return pd.DataFrame()

        self._purchase_sequences = sequences
        self._train_purchase_embeddings(sequences)
        self._partner_embedding_matrix = self._compute_partner_embeddings(sequences)

        logger.info(
            f"[Embedding] ✓ Partner embedding matrix ready: "
            f"{self._partner_embedding_matrix.shape}"
        )
        return self._partner_embedding_matrix

    def reset_purchase_embeddings(self) -> None:
        """Call this at the start of each clustering run to force re-computation."""
        self._purchase_sequences = {}
        self._word2vec_model = None
        self._partner_embedding_matrix = None

    # ── Internal helpers ──────────────────────────────────────────────────────
    def _embeddings_enabled(self) -> bool:
        env_flag = str(getattr(self, "enable_purchase_embeddings", "true")).lower()
        if env_flag in ("false", "0", "no"):
            return False
        # Also disable in strict view-only or fast mode
        if getattr(self, "strict_view_only", False):
            return False
        return True

    def _load_purchase_sequences(self) -> dict:
        """
        Load ordered product purchase sequences per partner.
        Returns {company_name: [product_name, product_name, ...]} ordered by date.
        """
        lookback = int(getattr(self, "embedding_lookback_days", 365))
        query = text(
            f"""
            SELECT
                mp.company_name,
                p.product_name,
                t.date
            FROM transactions_dsr t
            JOIN transactions_dsr_products tp ON tp.dsr_id = t.id
            JOIN master_products p            ON p.id = tp.product_id
            JOIN master_party mp              ON mp.id = t.party_id
            WHERE LOWER(CAST(t.is_approved AS TEXT)) = 'true'
              AND t.date >= CURRENT_DATE - INTERVAL '{lookback} days'
            ORDER BY mp.company_name, t.date
            """
        )
        try:
            df = pd.read_sql(query, self.engine)
            if df.empty:
                logger.info("[Embedding] No raw transaction sequences found.")
                return {}
            sequences = (
                df.groupby("company_name")["product_name"]
                .apply(list)
                .to_dict()
            )
            logger.info(
                f"[Embedding] Loaded purchase sequences for {len(sequences)} partners "
                f"({len(df):,} line items, last {lookback} days)."
            )
            return sequences
        except Exception as exc:
            logger.warning(f"[Embedding] Failed to load sequences: {exc}")
            return {}

    def _train_purchase_embeddings(self, sequences: dict) -> None:
        """Train a lightweight Word2Vec model on the product sequences."""
        try:
            from gensim.models import Word2Vec
        except ImportError:
            logger.warning(
                "[Embedding] gensim not installed — purchase embeddings disabled. "
                "Run: pip install gensim"
            )
            return

        vector_size = int(getattr(self, "embedding_vector_size", 32))
        corpus = [seq for seq in sequences.values() if len(seq) >= 3]

        if len(corpus) < 5:
            logger.warning(
                f"[Embedding] Only {len(corpus)} usable sequences — "
                "need ≥5 with ≥3 purchases each. Skipping."
            )
            return

        try:
            self._word2vec_model = Word2Vec(
                sentences=corpus,
                vector_size=vector_size,
                window=5,
                min_count=2,
                workers=2,
                epochs=10,
                seed=42,
            )
            vocab_size = len(self._word2vec_model.wv)
            logger.info(
                f"[Embedding] Word2Vec trained: {len(corpus)} sequences, "
                f"{vocab_size} products, vector_size={vector_size}."
            )
        except Exception as exc:
            logger.warning(f"[Embedding] Word2Vec training failed: {exc}")

    def _compute_partner_embeddings(self, sequences: dict) -> pd.DataFrame:
        """
        Average all product vectors in a partner's sequence → one dense vector.
        Partners with no vocabulary coverage get a zero vector (not excluded).
        """
        if self._word2vec_model is None:
            return pd.DataFrame()

        wv = self._word2vec_model.wv
        dim = self._word2vec_model.vector_size
        records: dict = {}

        zero_vec = np.zeros(dim)
        for company, seq in sequences.items():
            known_vecs = [wv[p] for p in seq if p in wv]
            records[company] = (
                np.mean(known_vecs, axis=0) if known_vecs else zero_vec.copy()
            )

        if not records:
            return pd.DataFrame()

        df = pd.DataFrame.from_dict(records, orient="index")
        df.columns = [f"embed_{i:02d}" for i in range(dim)]
        df.index.name = "company_name"
        return df
