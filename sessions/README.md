# `sessions/` — Session Recording API

This module is the data-ingestion backbone of the monitoring server. It exposes a REST API for uploading complete GLSP interaction recording sessions, retrieving and filtering stored data, managing eye-tracking sessions, and storing screenshots for later heatmap generation.

---

## Demo

> `[ PLACEHOLDER — insert a GIF showing a session being uploaded and retrieved via the API or Swagger UI ]`
>
> ![Session upload demo](../docs/gifs/sessions_upload_demo.gif)

---

## Responsibility

| What it does | What it does NOT do |
|---|---|
| Stores raw interaction events exactly as sent by the frontend | Transform or interpret event semantics |
| Validates required fields and rejects duplicates | Enforce tool-specific business rules |
| Links eye-tracking sessions to recording sessions | Perform gaze fixation detection (done offline) |
| Provides filtered queries and aggregate statistics | Run usability analysis — see [`analysis/`](../analysis/README.md) |

---

## Database Schema

Five tables make up the sessions schema.

### `recording_sessions`

The root of every recording. Stores session-level metadata.

| Column | Type | Notes                                                                          |
|--------|------|--------------------------------------------------------------------------------|
| `id` | UUID | Internal primary key                                                           |
| `session_id` | VARCHAR | Frontend-provided unique ID (e.g. `activity_2026-01-05T18-20-42.100Z`)         |
| `tool_id` | VARCHAR | Which GLSP tool produced this session                                          |
| `tool_version` | VARCHAR | Tool version string                                                            |
| `editor_type` | VARCHAR | Diagram type (`activity`, `class`, `bpmn`, …)                                  |
| `model_file` | VARCHAR | Filename of the open model                                                     |
| `user_name` | VARCHAR | Participant identifier - this can be a random string or a hashed username etc. |
| `workspace` | VARCHAR | Workspace / study group                                                        |
| `start_time` / `end_time` | TIMESTAMPTZ | Session boundaries                                                             |
| `duration_ms` | INTEGER | Computed automatically                                                         |
| `total_events` | INTEGER | Event count at upload time                                                     |
| `extra_data` | JSONB | Tool-specific metadata (extensible)                                            |

### `interaction_events`

One row per user action. Ordered by `sequence_number` within a session.

| Column | Type | Notes |
|--------|------|-------|
| `event_type` | VARCHAR | Generic type (`element_create`, `element_select`, `viewport_change`, …) |
| `event_kind` | VARCHAR | GLSP action kind (`createNode`, `elementSelected`, `setViewport`, …) |
| `element_id` | VARCHAR | Denormalized for fast filtering |
| `element_type` | VARCHAR | e.g. `ACTIVITY__OpaqueAction`, `BPMNTask` |
| `position_x` / `position_y` | FLOAT | Canvas coordinates for spatial analysis |
| `data` | JSONB | Full raw event payload — never truncated |

### `gaze_points`

Raw eye-tracking samples at millisecond resolution. Can be linked to either a `recording_session` or a standalone `eye_tracking_session`.

### `eye_tracking_sessions`

Metadata wrapper for a batch of gaze points. Stores screen dimensions, tracker type, calibration info, and optionally links back to a `recording_session`.

### `clickstream_segments`

Pre-computed event subsequences. Used for pattern matching and behavioral clustering in offline analysis workflows.

---

## API Reference

All endpoints require a `Bearer <token>` header when `API_KEY` is set in the environment.

---

### Upload a Session

```http
POST /sessions
Content-Type: application/json
```

Accepts a complete session export from any GLSP frontend tool and persists it atomically.

**Request body:**

```json
{
  "session": {
    "sessionId": "activity_2026-01-05T18-20-42.100Z",
    "startTime": "2026-01-05T18:20:42.100Z",
    "endTime":   "2026-01-05T18:22:02.521Z",
    "toolId":    "bigUML",
    "toolVersion": "0.6.3",
    "editorType":  "activity",
    "modelFile":   "process.uml",
    "user":        "participant_01",
    "workspace":   "study_group_A"
  },
  "events": [
    {
      "type":      "element_create",
      "timestamp": "2026-01-05T18:20:43.100Z",
      "data": {
        "kind":          "createNode",
        "elementTypeId": "ACTIVITY__OpaqueAction",
        "location":      { "x": 120, "y": 240 }
      }
    }
  ]
}
```

**Required fields:** `sessionId`, `startTime`, `toolId`

**Response `201`:**

```json
{
  "success": true,
  "session_id": "activity_2026-01-05T18-20-42.100Z",
  "internal_id": "uuid",
  "tool_id": "bigUML",
  "events_stored": 87,
  "message": "Successfully stored bigUML/activity session with 87 events"
}
```

Returns `409 Conflict` if the `session_id` already exists.

---

### List Sessions

```http
GET /sessions
```

| Query param | Type | Description |
|-------------|------|-------------|
| `tool_id` | string | Filter by tool identifier |
| `editor_type` | string | Filter by diagram type |
| `user_name` | string | Filter by participant |
| `start_date` | ISO datetime | Sessions starting after this date |
| `end_date` | ISO datetime | Sessions starting before this date |
| `page` | int (≥ 1) | Page number (default 1) |
| `page_size` | int (1–100) | Results per page (default 20) |

---

### Aggregate Statistics

```http
GET /sessions/stats?tool_id=bigUML
```

Returns counts, breakdowns by tool / editor type / user, average duration, and event-type distribution across all stored sessions.

```json
{
  "total_sessions": 42,
  "total_events": 3840,
  "sessions_by_tool": { "bigUML": 35, "bpmn-glsp": 7 },
  "sessions_by_editor_type": { "activity": 20, "class": 15, "bpmn": 7 },
  "sessions_by_user": { "participant_01": 18, "participant_02": 24 },
  "avg_session_duration_ms": 91200,
  "avg_events_per_session": 91.4
}
```

---

### Get Session Detail

```http
GET /sessions/{session_id}?include_events=true
```

The `session_id` can be either the internal UUID or the frontend session ID string.

---

### Get Session Events (Filtered)

```http
GET /sessions/{session_id}/events
```

| Query param | Description |
|-------------|-------------|
| `event_type` | Filter by generic type |
| `event_kind` | Filter by GLSP action kind |
| `element_id` | Filter by element |
| `element_type` | Filter by element type |
| `start_sequence` / `end_sequence` | Slice by sequence number |
| `limit` | Cap results (max 10 000) |

---

### Delete a Session

```http
DELETE /sessions/{session_id}
```

Cascades to all associated `interaction_events`, `gaze_points`, and linked eye-tracking data.

---

### Upload Eye-Tracking Session

```http
POST /sessions/eye-tracking
Content-Type: application/json
```

```json
{
  "linkedSessionId": "activity_2026-01-05T18-20-42.100Z",
  "metadata": {
    "exportTime":        "2026-01-05T18:22:10.000Z",
    "duration":          90000,
    "totalPoints":       8100,
    "trackerType":       "webgazer",
    "screenWidth":       1920,
    "screenHeight":      1080,
    "calibrationPoints": 9
  },
  "gazePoints": [
    { "timestamp": 1736099042100, "x": 854.2, "y": 421.7 }
  ]
}
```

`linkedSessionId` is optional. When provided the eye-tracking session is linked to the corresponding recording session, enabling combined interaction + gaze analysis.

---

### Upload Screenshot

```http
POST /sessions/screenshot
Content-Type: application/json
```

```json
{
  "linkedSessionId": "activity_2026-01-05T18-20-42.100Z",
  "timestamp":       "2026-01-05T18:20:42.100Z",
  "imageData":       "<base64-encoded PNG>"
}
```

Screenshots are stored on disk under `sessions/screenshots/` and are automatically discovered by the heatmap generator in the `analysis` module.

---

## Common Event Types

These event types and kinds are used consistently across GLSP tools. The API does not enforce them — they are conventions.

| `event_type` | `event_kind` | Description |
|---|---|---|
| `session_start` | — | Recording started |
| `session_end` | — | Recording ended |
| `element_create` | `createNode` | Node added to diagram |
| `element_create` | `createEdge` | Edge added to diagram |
| `element_select` | `elementSelected` | Element(s) selected |
| `element_delete` | `deleteElement` | Element(s) deleted |
| `element_move` | `changeBounds` | Element moved or resized |
| `property_change` | `applyLabelEdit` | Label changed |
| `property_change` | `updateElementProperty` | Property updated |
| `viewport_change` | `setViewport` | Canvas panned or zoomed |

