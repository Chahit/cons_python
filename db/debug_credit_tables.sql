
-- STEP 1: Test due_payment → transactions_dsr join
-- (Some due_payment rows have dsr_id = NULL, so we need LEFT JOIN)
SELECT COUNT(*) AS due_payment_rows,
       COUNT(dp.dsr_id) AS with_dsr_id,
       COUNT(t.party_id) AS matched_to_party
FROM due_payment dp
LEFT JOIN transactions_dsr t ON t.id = dp.dsr_id
WHERE dp.is_active = TRUE
  AND dp.deleted_at IS NULL;

-- STEP 2: Check if contact_id in due_payment maps to master_party
SELECT COUNT(*) AS contact_id_rows
FROM due_payment dp
WHERE dp.contact_id IS NOT NULL;

-- STEP 3: Check due_payment_amount structure
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'due_payment_amount'
ORDER BY ordinal_position;

-- STEP 4: Check due_advance_payment_dueadvancepayment columns
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'due_advance_payment_dueadvancepayment'
ORDER BY ordinal_position;

-- STEP 5: Check master_party_credit_details columns
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'master_party_credit_details'
ORDER BY ordinal_position;
