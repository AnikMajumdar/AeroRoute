-- ML training pipeline schema enhancements
ALTER TABLE model_training_samples ADD COLUMN IF NOT EXISTS route_request_id UUID REFERENCES route_requests (id) ON DELETE SET NULL;
ALTER TABLE model_training_samples ADD COLUMN IF NOT EXISTS model_target TEXT;
ALTER TABLE model_training_samples ADD COLUMN IF NOT EXISTS label_source TEXT;
ALTER TABLE model_training_samples ADD COLUMN IF NOT EXISTS dataset_version TEXT DEFAULT 'v1';

-- Rename labels column alias: keep labels JSONB, features JSONB
-- Add model_version to predictions
ALTER TABLE model_predictions ADD COLUMN IF NOT EXISTS model_version TEXT;
ALTER TABLE model_predictions ADD COLUMN IF NOT EXISTS features JSONB;

CREATE INDEX IF NOT EXISTS idx_training_samples_target ON model_training_samples (model_target);
CREATE INDEX IF NOT EXISTS idx_training_samples_dataset ON model_training_samples (dataset_version);
CREATE INDEX IF NOT EXISTS idx_predictions_model ON model_predictions (model_name, model_version);
