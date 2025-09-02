CREATE DATABASE IF NOT EXISTS recipe_recommender;
USE recipe_recommender;

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Recipes table
CREATE TABLE IF NOT EXISTS recipes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    recipe_name VARCHAR(255) NOT NULL,
    ingredients TEXT NOT NULL,
    instructions TEXT NOT NULL,
    user_id INT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Insert sample user (password is 'password123' hashed)
INSERT INTO users (name, email, password) VALUES 
('Demo User', 'demo@example.com', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewdBVdM3DtLlZn8.');

-- Insert sample recipes
INSERT INTO recipes (recipe_name, ingredients, instructions, user_id) VALUES 
('Simple Chicken Pasta', 'chicken, pasta, tomatoes, garlic', 'Cook pasta. Sauté chicken with garlic. Add tomatoes. Combine with pasta.', 1),
('Tomato Basil Salad', 'tomatoes, basil, olive oil, salt', 'Slice tomatoes. Add fresh basil. Drizzle with olive oil and salt.', 1);
