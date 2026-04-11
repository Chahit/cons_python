"""
Graph Embeddings Mixin — SVD-based partner similarity.

Builds a bipartite partner ↔ product-group graph weighted by spend,
projects it to a partner–partner cosine-similarity space via
Truncated SVD (numpy/scipy only — no extra dependencies).

Public API:
    get_similar_partners(partner_name, top_k=5)  → list[dict]
    get_partner_embedding(partner_name)           → np.ndarray | None
    get_all_embeddings()                          → pd.DataFrame (index=company_name)
"""

from __future__ import annotations

import numpy as np
import pandas as pd


class GraphEmbeddingsMixin:

    # ------------------------------------------------------------------ #
    #  State                                                               #
    # ------------------------------------------------------------------ #
    _graph_embeddings: pd.DataFrame | None = None   # (n_partners, n_dims)
    _graph_similarity: np.ndarray | None = None     # (n_partners, n_partners)
    _graph_partner_index: list[str] = []
    _graph_ready: bool = False

    # ------------------------------------------------------------------ #
    #  Build                                                               #
    # ------------------------------------------------------------------ #

    def build_graph_embeddings(self, n_components: int = 32) -> dict:
        """
        Build truncated-SVD embeddings from the partner × product-group
        spend matrix.  Requires df_recent_group_spend to be loaded.

        Parameters
        ----------
        n_components : int
            Embedding dimensionality (latent factors).  Capped at
            min(n_partners, n_groups) - 1 automatically.

        Returns
        -------
        dict  —  report with status, n_partners, n_groups, n_components used.
        """
        self._graph_ready = False
        rgs = getattr(self, "df_recent_group_spend", None)
        if rgs is None or rgs.empty:
            return {"status": "no_data", "reason": "df_recent_group_spend not loaded."}

        # Build spend pivot: rows = partners, cols = product groups
        try:
            pivot = rgs.pivot_table(
                index="company_name",
                columns="group_name",
                values="total_spend",
                aggfunc="sum",
                fill_value=0.0,
            )
        except Exception as e:
            return {"status": "error", "reason": f"Pivot failed: {e}"}

        if pivot.shape[0] < 3 or pivot.shape[1] < 2:
            return {
                "status": "insufficient_data",
                "reason": f"Too few partners ({pivot.shape[0]}) or groups ({pivot.shape[1]}).",
            }

        partner_names = list(pivot.index)
        X = pivot.values.astype(float)

        # Log-scale to reduce dominance of high-spend outliers
        X = np.log1p(X)

        # L2-normalise rows so cosine similarity = dot product
        norms = np.linalg.norm(X, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        X_normed = X / norms

        # Truncated SVD via numpy (economy SVD)
        n_comp = min(n_components, X.shape[0] - 1, X.shape[1] - 1)
        n_comp = max(n_comp, 2)

        try:
            U, s, Vt = np.linalg.svd(X_normed, full_matrices=False)
            # Keep top-n_comp components
            U_k = U[:, :n_comp]          # (n_partners, n_comp)
            s_k = s[:n_comp]             # (n_comp,)
            embeddings = U_k * s_k       # weighted by singular values
        except Exception as e:
            return {"status": "error", "reason": f"SVD failed: {e}"}

        # L2-normalise embeddings for cosine similarity via dot product
        emb_norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        emb_norms = np.where(emb_norms == 0, 1.0, emb_norms)
        embeddings_normed = embeddings / emb_norms

        # Pre-compute full cosine similarity matrix
        sim_matrix = embeddings_normed @ embeddings_normed.T
        np.fill_diagonal(sim_matrix, 0.0)   # exclude self

        self._graph_embeddings = pd.DataFrame(
            embeddings,
            index=partner_names,
            columns=[f"svd_{i}" for i in range(n_comp)],
        )
        self._graph_similarity = sim_matrix
        self._graph_partner_index = partner_names
        self._graph_ready = True

        return {
            "status": "ok",
            "n_partners": len(partner_names),
            "n_groups": pivot.shape[1],
            "n_components": int(n_comp),
            "variance_explained": float(np.sum(s_k ** 2) / np.sum(s ** 2))
            if len(s) > 0 else None,
        }

    # ------------------------------------------------------------------ #
    #  Query                                                               #
    # ------------------------------------------------------------------ #

    def get_similar_partners(
        self,
        partner_name: str,
        top_k: int = 5,
        exclude_same_cluster: bool = False,
    ) -> list[dict]:
        """
        Return top-k most similar partners by SVD-based cosine similarity.

        Parameters
        ----------
        partner_name : str
        top_k : int
        exclude_same_cluster : bool
            If True and ai.matrix exists, skip partners in the same cluster.

        Returns
        -------
        list of dicts with keys: partner, similarity, cluster_label, cluster_type
        """
        if not self._graph_ready:
            self.build_graph_embeddings()

        if not self._graph_ready or self._graph_similarity is None:
            return []

        idx_map = {p: i for i, p in enumerate(self._graph_partner_index)}
        if partner_name not in idx_map:
            return []

        i = idx_map[partner_name]
        sims = self._graph_similarity[i].copy()

        # Optional: exclude same-cluster partners
        own_cluster = None
        if exclude_same_cluster:
            try:
                matrix = getattr(self, "matrix", None)
                if matrix is not None and partner_name in matrix.index:
                    own_cluster = str(matrix.loc[partner_name, "cluster_label"])
            except Exception:
                pass

        results = []
        ranked = np.argsort(sims)[::-1]
        for j in ranked:
            if j == i:
                continue
            peer = self._graph_partner_index[j]
            sim_val = float(sims[j])
            if sim_val <= 0:
                break

            cluster_label = ""
            cluster_type = ""
            try:
                matrix = getattr(self, "matrix", None)
                if matrix is not None and peer in matrix.index:
                    cluster_label = str(matrix.loc[peer, "cluster_label"])
                    cluster_type = str(matrix.loc[peer, "cluster_type"])
                    if exclude_same_cluster and own_cluster and cluster_label == own_cluster:
                        continue
            except Exception:
                pass

            results.append({
                "partner": peer,
                "similarity": round(sim_val, 4),
                "cluster_label": cluster_label,
                "cluster_type": cluster_type,
            })
            if len(results) >= top_k:
                break

        return results

    def get_partner_embedding(self, partner_name: str) -> np.ndarray | None:
        """Return raw SVD embedding vector for a single partner."""
        if not self._graph_ready or self._graph_embeddings is None:
            return None
        if partner_name not in self._graph_embeddings.index:
            return None
        return self._graph_embeddings.loc[partner_name].values.copy()

    def get_all_embeddings(self) -> pd.DataFrame:
        """Return the full embedding DataFrame (index = company_name)."""
        if self._graph_embeddings is None:
            return pd.DataFrame()
        return self._graph_embeddings.copy()

    def ensure_graph_embeddings(self) -> dict:
        """Lazily build graph embeddings if not already done."""
        if self._graph_ready:
            return {"status": "already_built"}
        return self.build_graph_embeddings()
