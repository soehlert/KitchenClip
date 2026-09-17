/**
 * Dynamic Ingredient and Instruction management for Recipe Scratch Creation
 */
document.addEventListener('DOMContentLoaded', function () {
    const ingredientsList = document.getElementById('ingredients-list');
    const addIngredientBtn = document.getElementById('add-ingredient-btn');
    const instructionsList = document.getElementById('instructions-list');
    const addInstructionBtn = document.getElementById('add-instruction-btn');

    function createIngredientRow(quantity = '', unit = '', food = '') {
        const row = document.createElement('div');
        row.className = 'ingredient-row flex gap-2 items-center bg-white p-2 rounded-lg border border-[#D7EEF2]';
        row.innerHTML = `
            <div class="w-1/4">
                <input type="text" name="ingredient_quantity" placeholder="Qty (e.g. 1 1/2)" aria-label="Quantity" class="w-full px-2 py-1.5 border border-[#5B8E7D] rounded bg-white text-sm focus:outline-none focus:ring-1 focus:ring-[#194769] text-[#194769]" />
            </div>
            <div class="w-1/4">
                <input type="text" name="ingredient_unit" placeholder="Unit (e.g. cup, tsp)" aria-label="Unit" class="w-full px-2 py-1.5 border border-[#5B8E7D] rounded bg-white text-sm focus:outline-none focus:ring-1 focus:ring-[#194769] text-[#194769]" />
            </div>
            <div class="flex-1">
                <input type="text" name="ingredient_food" placeholder="Ingredient name (e.g. all-purpose flour)" aria-label="Ingredient name" class="w-full px-2 py-1.5 border border-[#5B8E7D] rounded bg-white text-sm focus:outline-none focus:ring-1 focus:ring-[#194769] text-[#194769]" />
            </div>
            <button type="button" class="remove-ingredient-btn text-[#F2855E] hover:text-[#D73A49] p-1.5 rounded hover:bg-red-50 transition" title="Remove ingredient" aria-label="Remove ingredient">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
            </button>
        `;
        row.querySelector('input[name="ingredient_quantity"]').value = quantity;
        row.querySelector('input[name="ingredient_unit"]').value = unit;
        row.querySelector('input[name="ingredient_food"]').value = food;
        return row;
    }

    if (addIngredientBtn && ingredientsList) {
        addIngredientBtn.addEventListener('click', function () {
            const newRow = createIngredientRow();
            ingredientsList.appendChild(newRow);
            const qtyInput = newRow.querySelector('input[name="ingredient_quantity"]');
            if (qtyInput) qtyInput.focus();
        });

        ingredientsList.addEventListener('click', function (e) {
            const removeBtn = e.target.closest('.remove-ingredient-btn');
            if (removeBtn) {
                const row = removeBtn.closest('.ingredient-row');
                if (row) {
                    row.remove();
                }
            }
        });

        ingredientsList.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
                const target = e.target;
                if (target && (target.name === 'ingredient_quantity' || target.name === 'ingredient_unit' || target.name === 'ingredient_food')) {
                    e.preventDefault();
                    const currentRow = target.closest('.ingredient-row');
                    const nextRow = currentRow ? currentRow.nextElementSibling : null;
                    if (nextRow && nextRow.classList.contains('ingredient-row')) {
                        const nextInput = nextRow.querySelector('input[name="ingredient_quantity"]');
                        if (nextInput) nextInput.focus();
                    } else if (addIngredientBtn) {
                        addIngredientBtn.click();
                    }
                }
            }
        });
    }

    function renumberSteps() {
        if (!instructionsList) return;
        const rows = instructionsList.querySelectorAll('.instruction-row');
        rows.forEach((row, index) => {
            const badge = row.querySelector('.step-badge');
            if (badge) {
                badge.textContent = index + 1;
            }
        });
    }

    function createInstructionRow(text = '') {
        const row = document.createElement('div');
        row.className = 'instruction-row flex gap-2 items-start bg-white p-2 rounded-lg border border-[#D7EEF2]';
        row.innerHTML = `
            <span class="step-badge mt-1.5 flex items-center justify-center w-6 h-6 rounded-full bg-[#194769] text-white text-xs font-bold shrink-0">1</span>
            <textarea name="instruction_step" rows="2" placeholder="Describe this cooking step..." aria-label="Instruction step" class="w-full px-2 py-1.5 border border-[#5B8E7D] rounded bg-white text-sm focus:outline-none focus:ring-1 focus:ring-[#194769] text-[#194769]"></textarea>
            <button type="button" class="remove-instruction-btn text-[#F2855E] hover:text-[#D73A49] p-1.5 rounded hover:bg-red-50 transition mt-1" title="Remove step" aria-label="Remove step">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
            </button>
        `;
        row.querySelector('textarea[name="instruction_step"]').value = text;
        return row;
    }

    if (addInstructionBtn && instructionsList) {
        addInstructionBtn.addEventListener('click', function () {
            const newRow = createInstructionRow();
            instructionsList.appendChild(newRow);
            renumberSteps();
            const textarea = newRow.querySelector('textarea');
            if (textarea) textarea.focus();
        });

        instructionsList.addEventListener('click', function (e) {
            const removeBtn = e.target.closest('.remove-instruction-btn');
            if (removeBtn) {
                const row = removeBtn.closest('.instruction-row');
                if (row) {
                    row.remove();
                    renumberSteps();
                }
            }
        });
    }

    renumberSteps();
});
