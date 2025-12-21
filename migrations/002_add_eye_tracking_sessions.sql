-- Migration: 002_add_eye_tracking_sessions.sql
-- Description: Add eye-tracking session table to link eye-tracking data with interaction sessions

-- ============================================================================
-- Eye Tracking Sessions Table
-- ============================================================================

CREATE TABLE IF NOT EXISTS eye_tracking_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Link to interaction recording session (optional - can be standalone)
    recording_session_id UUID REFERENCES recording_sessions(id) ON DELETE SET NULL,
    
    -- Eye tracking session identification
    session_id VARCHAR(255) NOT NULL,  -- Can be same as recording session or standalone
    
    -- Timing
    start_time TIMESTAMP WITH TIME ZONE NOT NULL,
    end_time TIMESTAMP WITH TIME ZONE,
    duration_ms INTEGER,
    
    -- Statistics
    total_gaze_points INTEGER DEFAULT 0,
    total_fixations INTEGER DEFAULT 0,
    avg_confidence FLOAT,
    
    -- Metadata
    tracker_type VARCHAR(100),  -- e.g., "webgazer", "tobii", "eyelink"
    screen_width INTEGER,
    screen_height INTEGER,
    calibration_points INTEGER,
    
    -- Upload metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    extra_data JSONB
);

-- Indexes for eye_tracking_sessions
CREATE INDEX IF NOT EXISTS ix_eye_tracking_sessions_session_id ON eye_tracking_sessions(session_id);
CREATE INDEX IF NOT EXISTS ix_eye_tracking_sessions_recording_session ON eye_tracking_sessions(recording_session_id);
CREATE INDEX IF NOT EXISTS ix_eye_tracking_sessions_start_time ON eye_tracking_sessions(start_time);

-- ============================================================================
-- Update gaze_points to reference eye_tracking_sessions instead of recording_sessions
-- Add eye_tracking_session_id column (keeping session_id for backward compatibility)
-- ============================================================================

ALTER TABLE gaze_points 
ADD COLUMN IF NOT EXISTS eye_tracking_session_id UUID REFERENCES eye_tracking_sessions(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS ix_gaze_points_eye_tracking_session ON gaze_points(eye_tracking_session_id);

-- ============================================================================
-- Update Trigger for eye_tracking_sessions.updated_at
-- ============================================================================

DROP TRIGGER IF EXISTS update_eye_tracking_sessions_updated_at ON eye_tracking_sessions;
CREATE TRIGGER update_eye_tracking_sessions_updated_at
    BEFORE UPDATE ON eye_tracking_sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
