
/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;
DROP TABLE IF EXISTS `answer_records`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `answer_records` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `public_id` varchar(40) NOT NULL,
  `attempt_id` bigint NOT NULL,
  `question_id` bigint NOT NULL,
  `selected_answers_json` json NOT NULL,
  `is_correct` tinyint(1) NOT NULL,
  `duration_ms` int NOT NULL,
  `idempotency_key` varchar(64) NOT NULL,
  `answered_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_answer_attempt_question` (`attempt_id`,`question_id`),
  UNIQUE KEY `uq_answer_attempt_idempotency` (`attempt_id`,`idempotency_key`),
  UNIQUE KEY `public_id` (`public_id`),
  KEY `question_id` (`question_id`),
  CONSTRAINT `answer_records_ibfk_1` FOREIGN KEY (`attempt_id`) REFERENCES `learning_attempts` (`id`) ON DELETE CASCADE,
  CONSTRAINT `answer_records_ibfk_2` FOREIGN KEY (`question_id`) REFERENCES `questions` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `attempt_questions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `attempt_questions` (
  `attempt_id` bigint NOT NULL,
  `question_id` bigint NOT NULL,
  `sequence_no` int NOT NULL,
  PRIMARY KEY (`attempt_id`,`question_id`),
  UNIQUE KEY `uq_attempt_question_sequence` (`attempt_id`,`sequence_no`),
  KEY `question_id` (`question_id`),
  CONSTRAINT `attempt_questions_ibfk_1` FOREIGN KEY (`attempt_id`) REFERENCES `learning_attempts` (`id`) ON DELETE CASCADE,
  CONSTRAINT `attempt_questions_ibfk_2` FOREIGN KEY (`question_id`) REFERENCES `questions` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `auth_sessions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `auth_sessions` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `public_id` varchar(40) NOT NULL,
  `user_id` bigint NOT NULL,
  `refresh_token_hash` varchar(64) NOT NULL,
  `expires_at` datetime NOT NULL,
  `last_used_at` datetime DEFAULT NULL,
  `revoked_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `public_id` (`public_id`),
  UNIQUE KEY `refresh_token_hash` (`refresh_token_hash`),
  KEY `ix_auth_sessions_user_active` (`user_id`,`revoked_at`,`expires_at`),
  CONSTRAINT `auth_sessions_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `knowledge_domains`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `knowledge_domains` (
  `id` int NOT NULL AUTO_INCREMENT,
  `code` varchar(32) NOT NULL,
  `name` varchar(32) NOT NULL,
  `sort_order` int NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `code` (`code`),
  UNIQUE KEY `name` (`name`)
) ENGINE=InnoDB AUTO_INCREMENT=8 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `learning_attempts`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `learning_attempts` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `public_id` varchar(40) NOT NULL,
  `user_id` bigint NOT NULL,
  `quiz_id` bigint DEFAULT NULL,
  `attempt_type` varchar(16) NOT NULL,
  `status` varchar(16) NOT NULL,
  `current_sequence` int NOT NULL,
  `correct_count` int NOT NULL,
  `total_count` int NOT NULL,
  `accuracy` int NOT NULL,
  `earned_xp` int NOT NULL,
  `total_duration_ms` bigint NOT NULL,
  `started_at` datetime NOT NULL,
  `completed_at` datetime DEFAULT NULL,
  `abandoned_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `public_id` (`public_id`),
  KEY `quiz_id` (`quiz_id`),
  KEY `ix_attempts_user_status_started` (`user_id`,`status`,`started_at`,`id`),
  CONSTRAINT `learning_attempts_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
  CONSTRAINT `learning_attempts_ibfk_2` FOREIGN KEY (`quiz_id`) REFERENCES `quizzes` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `learning_reports`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `learning_reports` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `public_id` varchar(40) NOT NULL,
  `attempt_id` bigint NOT NULL,
  `mastered_points_json` json NOT NULL,
  `weak_points_json` json NOT NULL,
  `three_line_summary_json` json NOT NULL,
  `advice_json` json NOT NULL,
  `share_quote` varchar(80) NOT NULL,
  `model_name` varchar(64) DEFAULT NULL,
  `prompt_version` varchar(32) DEFAULT NULL,
  `created_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `public_id` (`public_id`),
  UNIQUE KEY `attempt_id` (`attempt_id`),
  CONSTRAINT `learning_reports_ibfk_1` FOREIGN KEY (`attempt_id`) REFERENCES `learning_attempts` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `mistake_records`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `mistake_records` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `user_id` bigint NOT NULL,
  `question_id` bigint NOT NULL,
  `wrong_count` int NOT NULL,
  `review_success_count` int NOT NULL,
  `review_stage` int NOT NULL,
  `status` varchar(16) NOT NULL,
  `first_wrong_at` datetime NOT NULL,
  `last_wrong_at` datetime NOT NULL,
  `last_reviewed_at` datetime DEFAULT NULL,
  `next_review_at` datetime DEFAULT NULL,
  `mastered_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_mistake_user_question` (`user_id`,`question_id`),
  KEY `question_id` (`question_id`),
  KEY `ix_mistakes_due` (`user_id`,`status`,`next_review_at`),
  CONSTRAINT `mistake_records_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
  CONSTRAINT `mistake_records_ibfk_2` FOREIGN KEY (`question_id`) REFERENCES `questions` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `questions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `questions` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `public_id` varchar(40) NOT NULL,
  `quiz_id` bigint NOT NULL,
  `sequence_no` int NOT NULL,
  `question_type` varchar(16) NOT NULL,
  `stem` varchar(500) NOT NULL,
  `options_json` json NOT NULL,
  `answer_json` json NOT NULL,
  `explanation` varchar(1200) NOT NULL,
  `knowledge_point` varchar(80) NOT NULL,
  `difficulty` varchar(16) NOT NULL,
  `created_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_question_quiz_sequence` (`quiz_id`,`sequence_no`),
  UNIQUE KEY `public_id` (`public_id`),
  CONSTRAINT `questions_ibfk_1` FOREIGN KEY (`quiz_id`) REFERENCES `quizzes` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `quizzes`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `quizzes` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `public_id` varchar(40) NOT NULL,
  `user_id` bigint NOT NULL,
  `domain_id` int DEFAULT NULL,
  `source_type` varchar(16) NOT NULL,
  `user_input` text NOT NULL,
  `title` varchar(80) NOT NULL,
  `summary` varchar(300) NOT NULL,
  `question_count` int NOT NULL,
  `difficulty` varchar(16) NOT NULL,
  `generation_status` varchar(16) NOT NULL,
  `model_name` varchar(64) DEFAULT NULL,
  `prompt_version` varchar(32) DEFAULT NULL,
  `web_search_metadata_json` json DEFAULT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `public_id` (`public_id`),
  KEY `domain_id` (`domain_id`),
  KEY `ix_quizzes_user_created` (`user_id`,`created_at`),
  CONSTRAINT `quizzes_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
  CONSTRAINT `quizzes_ibfk_2` FOREIGN KEY (`domain_id`) REFERENCES `knowledge_domains` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `user_daily_stats`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `user_daily_stats` (
  `user_id` bigint NOT NULL,
  `stat_date` date NOT NULL,
  `completed_attempts` int NOT NULL,
  `answered_questions` int NOT NULL,
  `correct_answers` int NOT NULL,
  `learning_duration_ms` bigint NOT NULL,
  `earned_xp` int NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`user_id`,`stat_date`),
  CONSTRAINT `user_daily_stats_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `user_identities`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `user_identities` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `user_id` bigint NOT NULL,
  `provider` varchar(16) NOT NULL,
  `app_id` varchar(64) NOT NULL,
  `provider_subject` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `union_id` varchar(128) DEFAULT NULL,
  `last_login_at` datetime NOT NULL,
  `created_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_identity_provider_subject` (`provider`,`app_id`,`provider_subject`),
  KEY `user_id` (`user_id`),
  CONSTRAINT `user_identities_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `user_knowledge_progress`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `user_knowledge_progress` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `user_id` bigint NOT NULL,
  `domain_id` int NOT NULL,
  `knowledge_point` varchar(80) NOT NULL,
  `mastery` int NOT NULL,
  `status` varchar(16) NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_user_domain_point` (`user_id`,`domain_id`,`knowledge_point`),
  KEY `domain_id` (`domain_id`),
  CONSTRAINT `user_knowledge_progress_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
  CONSTRAINT `user_knowledge_progress_ibfk_2` FOREIGN KEY (`domain_id`) REFERENCES `knowledge_domains` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `users`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `users` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `public_id` varchar(40) NOT NULL,
  `nickname` varchar(24) NOT NULL,
  `avatar_url` varchar(500) NOT NULL,
  `profile_completed` tinyint(1) NOT NULL,
  `status` varchar(16) NOT NULL,
  `xp_total` int NOT NULL,
  `current_streak_days` int NOT NULL,
  `longest_streak_days` int NOT NULL,
  `last_learning_date` date DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `public_id` (`public_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `xp_transactions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `xp_transactions` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `user_id` bigint NOT NULL,
  `amount` int NOT NULL,
  `reason_type` varchar(32) NOT NULL,
  `business_id` varchar(64) NOT NULL,
  `created_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_xp_business` (`user_id`,`reason_type`,`business_id`),
  CONSTRAINT `xp_transactions_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;
