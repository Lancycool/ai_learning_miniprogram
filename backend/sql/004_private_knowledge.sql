-- 新增私有资料与原题表。已有库优先使用 Alembic 升级；此增量 SQL 只执行一次。
SET NAMES utf8mb4;

CREATE TABLE knowledge_bases (
	name VARCHAR(30) NOT NULL,
	description VARCHAR(300) NOT NULL,
	cover VARCHAR(20) NOT NULL,
	deleted_at DATETIME,
	id BIGINT NOT NULL AUTO_INCREMENT,
	public_id VARCHAR(40) NOT NULL,
	user_id BIGINT NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (public_id),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE INDEX ix_knowledge_bases_owner ON knowledge_bases (user_id, deleted_at, created_at);

CREATE TABLE knowledge_documents (
	knowledge_base_id BIGINT NOT NULL,
	title VARCHAR(120) NOT NULL,
	file_type VARCHAR(16) NOT NULL,
	file_size BIGINT NOT NULL,
	file_hash VARCHAR(64) NOT NULL,
	current_version_id BIGINT,
	parse_status VARCHAR(16) NOT NULL,
	index_status VARCHAR(16) NOT NULL,
	cleanup_status VARCHAR(16) NOT NULL,
	deleted_at DATETIME,
	id BIGINT NOT NULL AUTO_INCREMENT,
	public_id VARCHAR(40) NOT NULL,
	user_id BIGINT NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(knowledge_base_id) REFERENCES knowledge_bases (id) ON DELETE CASCADE,
	UNIQUE (public_id),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE INDEX ix_knowledge_documents_owner ON knowledge_documents (user_id, knowledge_base_id, deleted_at);

CREATE TABLE knowledge_document_versions (
	document_id BIGINT NOT NULL,
	version_no INTEGER NOT NULL,
	source_key VARCHAR(255) NOT NULL,
	parsed_key VARCHAR(255),
	text_length INTEGER NOT NULL,
	parse_warnings_json JSON NOT NULL,
	index_generation VARCHAR(40),
	embedding_fingerprint VARCHAR(64),
	chunk_count INTEGER NOT NULL,
	id BIGINT NOT NULL AUTO_INCREMENT,
	public_id VARCHAR(40) NOT NULL,
	user_id BIGINT NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_knowledge_version_number UNIQUE (document_id, version_no),
	FOREIGN KEY(document_id) REFERENCES knowledge_documents (id) ON DELETE CASCADE,
	UNIQUE (public_id),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE knowledge_chapters (
	version_id BIGINT NOT NULL,
	title VARCHAR(160) NOT NULL,
	sequence_no INTEGER NOT NULL,
	level INTEGER NOT NULL,
	parent_public_id VARCHAR(40),
	start_offset INTEGER NOT NULL,
	end_offset INTEGER NOT NULL,
	id BIGINT NOT NULL AUTO_INCREMENT,
	public_id VARCHAR(40) NOT NULL,
	user_id BIGINT NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_knowledge_chapter_sequence UNIQUE (version_id, sequence_no),
	CONSTRAINT ck_chapter_offsets CHECK (start_offset >= 0 AND end_offset > start_offset),
	FOREIGN KEY(version_id) REFERENCES knowledge_document_versions (id) ON DELETE CASCADE,
	UNIQUE (public_id),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE knowledge_processing_tasks (
	knowledge_base_id BIGINT NOT NULL,
	document_id BIGINT NOT NULL,
	version_id BIGINT NOT NULL,
	request_id VARCHAR(64) NOT NULL,
	task_type VARCHAR(24) NOT NULL,
	request_json JSON NOT NULL,
	status VARCHAR(16) NOT NULL,
	stage VARCHAR(24) NOT NULL,
	processed_count INTEGER NOT NULL,
	total_count INTEGER,
	claim_token VARCHAR(40),
	lease_expires_at DATETIME,
	started_at DATETIME,
	completed_at DATETIME,
	result_json JSON,
	error_code VARCHAR(40),
	error_message VARCHAR(200),
	id BIGINT NOT NULL AUTO_INCREMENT,
	public_id VARCHAR(40) NOT NULL,
	user_id BIGINT NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_knowledge_task_request UNIQUE (user_id, request_id),
	CONSTRAINT ck_knowledge_task_status CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
	FOREIGN KEY(knowledge_base_id) REFERENCES knowledge_bases (id) ON DELETE CASCADE,
	FOREIGN KEY(document_id) REFERENCES knowledge_documents (id) ON DELETE CASCADE,
	FOREIGN KEY(version_id) REFERENCES knowledge_document_versions (id) ON DELETE CASCADE,
	UNIQUE (public_id),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE INDEX ix_knowledge_tasks_document ON knowledge_processing_tasks (document_id, status);

CREATE INDEX ix_knowledge_tasks_queue ON knowledge_processing_tasks (status, created_at, id);

CREATE TABLE question_import_drafts (
	document_id BIGINT NOT NULL,
	version_id BIGINT NOT NULL,
	title VARCHAR(80) NOT NULL,
	revision INTEGER NOT NULL,
	chapter_ids_json JSON NOT NULL,
	items_json JSON NOT NULL,
	coverage_json JSON NOT NULL,
	issues_json JSON NOT NULL,
	id BIGINT NOT NULL AUTO_INCREMENT,
	public_id VARCHAR(40) NOT NULL,
	user_id BIGINT NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(document_id) REFERENCES knowledge_documents (id) ON DELETE CASCADE,
	FOREIGN KEY(version_id) REFERENCES knowledge_document_versions (id) ON DELETE CASCADE,
	UNIQUE (public_id),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE question_banks (
	document_id BIGINT NOT NULL,
	version_id BIGINT NOT NULL,
	draft_id BIGINT NOT NULL,
	draft_revision INTEGER NOT NULL,
	confirm_request_id VARCHAR(64) NOT NULL,
	title VARCHAR(80) NOT NULL,
	question_count INTEGER NOT NULL,
	id BIGINT NOT NULL AUTO_INCREMENT,
	public_id VARCHAR(40) NOT NULL,
	user_id BIGINT NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_question_bank_draft_revision UNIQUE (draft_id, draft_revision),
	CONSTRAINT uq_question_bank_confirmation UNIQUE (user_id, confirm_request_id),
	FOREIGN KEY(document_id) REFERENCES knowledge_documents (id) ON DELETE CASCADE,
	FOREIGN KEY(version_id) REFERENCES knowledge_document_versions (id) ON DELETE CASCADE,
	FOREIGN KEY(draft_id) REFERENCES question_import_drafts (id) ON DELETE RESTRICT,
	UNIQUE (public_id),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE question_bank_items (
	bank_id BIGINT NOT NULL,
	sequence_no INTEGER NOT NULL,
	chapter_id VARCHAR(40),
	question_type VARCHAR(16) NOT NULL,
	stem MEDIUMTEXT NOT NULL,
	options_json JSON NOT NULL,
	answer_json JSON NOT NULL,
	explanation MEDIUMTEXT,
	source_json JSON NOT NULL,
	id BIGINT NOT NULL AUTO_INCREMENT,
	public_id VARCHAR(40) NOT NULL,
	user_id BIGINT NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_question_bank_item_sequence UNIQUE (bank_id, sequence_no),
	FOREIGN KEY(bank_id) REFERENCES question_banks (id) ON DELETE CASCADE,
	UNIQUE (public_id),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE question_practice_groups (
	bank_id BIGINT NOT NULL,
	scope_hash VARCHAR(64) NOT NULL,
	chapter_ids_json JSON NOT NULL,
	group_index INTEGER NOT NULL,
	quiz_id BIGINT NOT NULL,
	id BIGINT NOT NULL AUTO_INCREMENT,
	public_id VARCHAR(40) NOT NULL,
	user_id BIGINT NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_question_practice_scope UNIQUE (bank_id, scope_hash, group_index),
	FOREIGN KEY(bank_id) REFERENCES question_banks (id) ON DELETE CASCADE,
	FOREIGN KEY(quiz_id) REFERENCES quizzes (id) ON DELETE RESTRICT,
	UNIQUE (public_id),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

ALTER TABLE knowledge_documents ADD CONSTRAINT fk_document_current_version FOREIGN KEY(current_version_id) REFERENCES knowledge_document_versions (id) ON DELETE SET NULL;

ALTER TABLE quizzes ADD COLUMN knowledge_metadata_json JSON NULL;
ALTER TABLE questions MODIFY stem MEDIUMTEXT NOT NULL,
  MODIFY explanation MEDIUMTEXT NOT NULL,
  ADD COLUMN source_metadata_json JSON NULL,
  ADD COLUMN original_item_id BIGINT NULL,
  ADD CONSTRAINT fk_question_original_item FOREIGN KEY (original_item_id)
    REFERENCES question_bank_items(id) ON DELETE SET NULL;
