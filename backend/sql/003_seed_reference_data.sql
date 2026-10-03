USE bamboo_quiz;
INSERT INTO knowledge_domains (code, name, sort_order) VALUES
('ai', '人工智能', 10), ('science', '自然科学', 20), ('economics', '经济常识', 30),
('history', '历史文化', 40), ('language', '语言学习', 50), ('life', '生活常识', 60), ('other', '其他', 70) AS incoming
ON DUPLICATE KEY UPDATE name = incoming.name, sort_order = incoming.sort_order;
