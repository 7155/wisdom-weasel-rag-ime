-- Bounded contract fixture for isolated lifecycle tests; NOT a replacement
-- for PAW migrations. Separate integration tests require the full checkout.
PRAGMA foreign_keys=ON;
CREATE TABLE input_events(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at_ms INTEGER NOT NULL,
 source TEXT NOT NULL,committed_text TEXT NOT NULL,recent_context TEXT NOT NULL DEFAULT '',preedit TEXT NOT NULL DEFAULT '',
 schema_id TEXT NOT NULL DEFAULT '',app TEXT NOT NULL DEFAULT '',project TEXT NOT NULL DEFAULT '',candidate_rank INTEGER,
 provider_name TEXT NOT NULL DEFAULT '',tags_json TEXT NOT NULL DEFAULT '[]',context_group_id TEXT NOT NULL DEFAULT '',
 context_group_level TEXT NOT NULL DEFAULT 'app',capture_metadata_json TEXT NOT NULL DEFAULT '{}');
CREATE TABLE memory_state(event_id INTEGER PRIMARY KEY REFERENCES input_events(id),deleted INTEGER DEFAULT 0,updated_at_ms INTEGER NOT NULL);
CREATE TABLE agent_memory_sources(source_id TEXT PRIMARY KEY,session_id TEXT NOT NULL DEFAULT '',pi_entry_id TEXT NOT NULL,
 input_event_id INTEGER REFERENCES input_events(id) ON DELETE RESTRICT,source_role TEXT NOT NULL,source_revision INTEGER DEFAULT 1,
 canonical_text_sha256 TEXT NOT NULL,status TEXT DEFAULT 'active',created_at_ms INTEGER NOT NULL,owner_kind TEXT DEFAULT 'user',
 owner_id TEXT DEFAULT 'default',source_kind TEXT NOT NULL,trust_class TEXT NOT NULL,disposition TEXT DEFAULT 'pending',
 disposition_reason TEXT DEFAULT '',disposition_updated_at_ms INTEGER NOT NULL,metadata_json TEXT DEFAULT '{}',
 knowledge_domain TEXT DEFAULT 'legacy',scope_kind TEXT DEFAULT 'legacy',scope_id TEXT DEFAULT '',visibility TEXT DEFAULT 'legacy',
 authorization_revision TEXT DEFAULT '',binding_id TEXT DEFAULT '',scope_mode TEXT DEFAULT 'legacy',
 UNIQUE(session_id,pi_entry_id,source_role,source_revision));
CREATE TABLE memory_source_disposition_events(event_id TEXT PRIMARY KEY,source_id TEXT REFERENCES agent_memory_sources(source_id) ON DELETE RESTRICT,
 previous_disposition TEXT,new_disposition TEXT,reason_code TEXT,actor_kind TEXT,created_at_ms INTEGER,metadata_json TEXT DEFAULT '{}');
CREATE TABLE agent_memory_evidence(evidence_id TEXT PRIMARY KEY,project TEXT NOT NULL DEFAULT '',role_id TEXT DEFAULT '',session_id TEXT DEFAULT '',
 source_kind TEXT NOT NULL CHECK(source_kind IN ('user_message','assistant_message','tool_receipt','session_digest','room_event','work_receipt')),
 source_id TEXT NOT NULL,idempotency_key TEXT NOT NULL,content_text TEXT NOT NULL,content_sha256 TEXT NOT NULL,provenance_json TEXT DEFAULT '{}',
 metadata_json TEXT DEFAULT '{}',privacy_class TEXT DEFAULT 'local' CHECK(privacy_class IN ('local','private')),
 status TEXT DEFAULT 'active' CHECK(status IN ('active','tombstoned')),occurred_at_ms INTEGER NOT NULL,recorded_at_ms INTEGER NOT NULL,
 owner_kind TEXT DEFAULT 'user',owner_id TEXT DEFAULT 'default',knowledge_domain TEXT DEFAULT 'legacy',scope_kind TEXT DEFAULT 'legacy',
 scope_id TEXT DEFAULT '',visibility TEXT DEFAULT 'legacy',authorization_revision TEXT DEFAULT '',binding_id TEXT DEFAULT '',scope_mode TEXT DEFAULT 'legacy',
 evidence_domain TEXT DEFAULT 'role_book',origin_kind TEXT DEFAULT 'legacy_agent_event',admission_state TEXT DEFAULT 'needs_review'
 CHECK(admission_state IN ('candidate','admitted','needs_review','rejected','forgotten')),admission_reason TEXT DEFAULT '',trust_class TEXT DEFAULT '',
 boundary_kind TEXT DEFAULT '',admission_revision INTEGER DEFAULT 1,admission_updated_at_ms INTEGER DEFAULT 0,forgotten_at_ms INTEGER,
 UNIQUE(project,source_kind,idempotency_key));
CREATE TABLE memory_evidence_input_event_links(evidence_id TEXT REFERENCES agent_memory_evidence(evidence_id) ON DELETE RESTRICT,
 input_event_id INTEGER REFERENCES input_events(id) ON DELETE RESTRICT,ordinal INTEGER DEFAULT 0,relation TEXT DEFAULT 'source',
 content_sha256 TEXT NOT NULL,created_at_ms INTEGER NOT NULL,PRIMARY KEY(evidence_id,input_event_id,relation));
CREATE TABLE memory_evidence_admission_events(event_id TEXT PRIMARY KEY,evidence_id TEXT REFERENCES agent_memory_evidence(evidence_id) ON DELETE RESTRICT,
 previous_state TEXT,new_state TEXT,reason_code TEXT,actor_kind TEXT,created_at_ms INTEGER,metadata_json TEXT DEFAULT '{}');
CREATE TABLE memory_atoms(id TEXT PRIMARY KEY,kind TEXT NOT NULL,text TEXT NOT NULL,canonical_text TEXT NOT NULL,
 source_event_ids_json TEXT DEFAULT '[]',source_memory_ids_json TEXT DEFAULT '[]',scope_app TEXT,scope_project TEXT,language TEXT DEFAULT 'zh',
 confidence REAL DEFAULT 0.5,quality_score REAL DEFAULT 0.5,echo_risk REAL DEFAULT 0,privacy_level TEXT DEFAULT 'local',status TEXT DEFAULT 'active',
 created_at_ms INTEGER NOT NULL,updated_at_ms INTEGER NOT NULL,last_used_at_ms INTEGER,owner_kind TEXT DEFAULT 'user',owner_id TEXT DEFAULT 'default',
 claim_key TEXT DEFAULT '',lineage_id TEXT DEFAULT '',claim_state TEXT DEFAULT 'current' CHECK(claim_state IN ('current','superseded','retracted')),
 valid_from_ms INTEGER DEFAULT 0,valid_to_ms INTEGER,supersedes_id TEXT);
CREATE TABLE memory_items(id INTEGER PRIMARY KEY,memory_id TEXT UNIQUE,source_event_id INTEGER,text TEXT DEFAULT '',owner_kind TEXT DEFAULT 'user',
 owner_id TEXT DEFAULT 'default',status TEXT DEFAULT 'active',updated_at_ms INTEGER DEFAULT 0);
CREATE TABLE memory_books(book_id TEXT PRIMARY KEY,source_event_ids_json TEXT DEFAULT '[]',memory_atom_ids_json TEXT DEFAULT '[]',owner_kind TEXT DEFAULT 'user',
 owner_id TEXT DEFAULT 'default',status TEXT DEFAULT 'active',updated_at_ms INTEGER DEFAULT 0);
CREATE TABLE memory_relations(relation_id TEXT PRIMARY KEY,owner_kind TEXT DEFAULT 'user',owner_id TEXT DEFAULT 'default',status TEXT DEFAULT 'active',revision INTEGER DEFAULT 1,updated_at_ms INTEGER DEFAULT 0);
CREATE TABLE memory_relation_sources(relation_id TEXT REFERENCES memory_relations(relation_id),source_type TEXT,source_id TEXT);
CREATE TABLE memory_tombstones(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at_ms INTEGER,target_type TEXT,target_value TEXT,reason TEXT DEFAULT '',active INTEGER DEFAULT 1,metadata_json TEXT DEFAULT '{}');
CREATE TABLE memory_maintenance_jobs(job_id TEXT PRIMARY KEY,state TEXT NOT NULL,request_json TEXT NOT NULL,result_json TEXT NOT NULL,progress_json TEXT NOT NULL,error TEXT DEFAULT '',
 created_at_ms INTEGER NOT NULL,updated_at_ms INTEGER NOT NULL,completed_at_ms INTEGER DEFAULT 0);
CREATE TABLE refresh_test_inputs(singleton INTEGER PRIMARY KEY,revision INTEGER NOT NULL);
INSERT INTO refresh_test_inputs VALUES(1,1);
CREATE TABLE refresh_test_effects(singleton INTEGER PRIMARY KEY,counter INTEGER NOT NULL);
INSERT INTO refresh_test_effects VALUES(1,0);
