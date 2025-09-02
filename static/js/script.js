class RecipeRecommender {
    constructor() {
        this.ingredientInput = document.getElementById('ingredientInput');
        this.getRecipesBtn = document.getElementById('getRecipesBtn');
        this.showMyRecipesBtn = document.getElementById('showMyRecipesBtn');
        this.recipesContainer = document.getElementById('recipesContainer');
        this.loadingSpinner = document.getElementById('loadingSpinner');
        
        this.initializeEventListeners();
    }
    
    initializeEventListeners() {
        // Get recipes button
        this.getRecipesBtn.addEventListener('click', () => this.getRecipes());
        
        // Enter key on input
        this.ingredientInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                this.getRecipes();
            }
        });
        
        // Ingredient tags
        document.querySelectorAll('.ingredient-tag').forEach(tag => {
            tag.addEventListener('click', () => {
                const ingredient = tag.dataset.ingredient;
                this.addIngredient(ingredient);
            });
        });
        
        // Show my recipes button
        this.showMyRecipesBtn.addEventListener('click', () => this.showMyRecipes());
    }
    
    addIngredient(ingredient) {
        const currentValue = this.ingredientInput.value;
        const ingredients = currentValue.split(',').map(i => i.trim()).filter(i => i);
        
        if (!ingredients.includes(ingredient)) {
            ingredients.push(ingredient);
            this.ingredientInput.value = ingredients.join(', ');
        }
        
        // Add visual feedback
        const tag = document.querySelector(`[data-ingredient="${ingredient}"]`);
        tag.style.transform = 'scale(0.95)';
        setTimeout(() => {
            tag.style.transform = 'translateY(-2px)';
        }, 100);
    }
    
    async getRecipes() {
        const ingredients = this.ingredientInput.value.trim();
        
        if (!ingredients) {
            this.showMessage('Please enter some ingredients!', 'error');
            return;
        }
        
        this.showLoading(true);
        this.recipesContainer.innerHTML = '';
        
        try {
            const response = await fetch('/get_recommendations', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ ingredients })
            });
            
            const data = await response.json();
            
            if (response.ok) {
                this.displayRecipes(data.recipes, 'AI Recommended Recipes');
            } else if (response.status === 402) {
                // Subscription required
                this.showMessage(data.error + ' Please upgrade your subscription.', 'error');
                // Redirect to subscription page after 2 seconds
                setTimeout(() => {
                    window.location.href = '/subscription';
                }, 2000);
            } else {
                this.showMessage(data.error || 'Failed to get recipes', 'error');
            }
        } catch (error) {
            console.error('Error:', error);
            this.showMessage('Network error. Please try again.', 'error');
        } finally {
            this.showLoading(false);
        }
    }
    
    async showMyRecipes() {
        this.showLoading(true);
        this.recipesContainer.innerHTML = '';
        
        try {
            const response = await fetch('/get_user_recipes');
            const data = await response.json();
            
            if (response.ok) {
                this.displayRecipes(data.recipes, 'My Saved Recipes', true);
            } else {
                this.showMessage(data.error || 'Failed to load your recipes', 'error');
            }
        } catch (error) {
            console.error('Error:', error);
            this.showMessage('Network error. Please try again.', 'error');
        } finally {
            this.showLoading(false);
        }
    }
    
    displayRecipes(recipes, title, showMeta = false) {
        if (recipes.length === 0) {
            this.recipesContainer.innerHTML = '<p style="text-align: center; color: #666; padding: 2rem;">No recipes found.</p>';
            return;
        }
        
        const recipesHTML = recipes.map(recipe => this.createRecipeCard(recipe, showMeta)).join('');
        this.recipesContainer.innerHTML = recipesHTML;
        
        // Add animation
        const cards = this.recipesContainer.querySelectorAll('.recipe-card');
        cards.forEach((card, index) => {
            card.style.opacity = '0';
            card.style.transform = 'translateY(20px)';
            setTimeout(() => {
                card.style.transition = 'all 0.5s ease';
                card.style.opacity = '1';
                card.style.transform = 'translateY(0)';
            }, index * 100);
        });
    }
    
    createRecipeCard(recipe, showMeta = false) {
        const metaHTML = showMeta ? `
            <div class="recipe-meta">
                <div>👤 Created by: ${recipe.user_name || 'You'}</div>
                <div>📅 ${recipe.created_at || 'Just now'}</div>
            </div>
        ` : '';
        
        return `
            <div class="recipe-card" onclick="this.classList.toggle('expanded')">
                <h3>${recipe.name || recipe.recipe_name}</h3>
                <div class="recipe-ingredients">
                    <strong>🥘 Ingredients:</strong> ${recipe.ingredients}
                </div>
                <div class="recipe-instructions">
                    <strong>👨‍🍳 Instructions:</strong><br>
                    ${recipe.instructions}
                </div>
                ${metaHTML}
            </div>
        `;
    }
    
    showLoading(show) {
        if (show) {
            this.loadingSpinner.classList.remove('hidden');
        } else {
            this.loadingSpinner.classList.add('hidden');
        }
    }
    
    showMessage(message, type = 'info') {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${type}`;
        messageDiv.textContent = message;
        
        // Style the message
        messageDiv.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 15px 20px;
            background: ${type === 'error' ? '#f8d7da' : '#d4edda'};
            color: ${type === 'error' ? '#721c24' : '#155724'};
            border-radius: 8px;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
            z-index: 1000;
            animation: slideIn 0.3s ease;
        `;
        
        document.body.appendChild(messageDiv);
        
        setTimeout(() => {
            messageDiv.style.animation = 'slideOut 0.3s ease';
            setTimeout(() => messageDiv.remove(), 300);
        }, 3000);
    }
}

// Initialize the app when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    new RecipeRecommender();
});

// Add CSS animations
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from { transform: translateX(100%); opacity: 0; }
        to { transform: translateX(0); opacity: 1; }
    }
    
    @keyframes slideOut {
        from { transform: translateX(0); opacity: 1; }
        to { transform: translateX(100%); opacity: 0; }
    }
    
    .recipe-card.expanded {
        transform: scale(1.02) !important;
        box-shadow: 0 12px 35px rgba(0, 0, 0, 0.2) !important;
        z-index: 10;
    }
`;