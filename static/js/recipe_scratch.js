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

    function getCsrfToken() {
        const csrfInput = document.querySelector('[name=csrfmiddlewaretoken]');
        if (csrfInput) return csrfInput.value;
        const cookie = document.cookie.split('; ').find(row => row.startsWith('csrftoken='));
        return cookie ? cookie.split('=')[1] : '';
    }

    async function parseIngredients(text) {
        const url = window.parseIngredientsUrl || '/api/recipes/parse-ingredients/';
        try {
            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken(),
                },
                body: JSON.stringify({ text: text }),
            });
            if (!response.ok) return null;
            const data = await response.json();
            return data.ingredients || [];
        } catch (err) {
            console.error('Failed to parse ingredients via API:', err);
            return null;
        }
    }

    function isRowEmpty(r) {
        const q = (r.querySelector('input[name="ingredient_quantity"]')?.value || '').trim();
        const u = (r.querySelector('input[name="ingredient_unit"]')?.value || '').trim();
        const f = (r.querySelector('input[name="ingredient_food"]')?.value || '').trim();
        return !q && !u && !f;
    }

    function applyParsedIngredients(currentRow, parsedList) {
        if (!parsedList || parsedList.length === 0) return;

        const first = parsedList[0];
        const qtyInput = currentRow.querySelector('input[name="ingredient_quantity"]');
        const unitInput = currentRow.querySelector('input[name="ingredient_unit"]');
        const foodInput = currentRow.querySelector('input[name="ingredient_food"]');

        if (qtyInput) qtyInput.value = first.quantity || '';
        if (unitInput) unitInput.value = first.unit || '';
        if (foodInput) foodInput.value = first.food || '';

        let prevRow = currentRow;
        for (let i = 1; i < parsedList.length; i++) {
            const item = parsedList[i];
            let targetRow = prevRow.nextElementSibling;
            if (targetRow && targetRow.classList.contains('ingredient-row') && isRowEmpty(targetRow)) {
                const tQty = targetRow.querySelector('input[name="ingredient_quantity"]');
                const tUnit = targetRow.querySelector('input[name="ingredient_unit"]');
                const tFood = targetRow.querySelector('input[name="ingredient_food"]');
                if (tQty) tQty.value = item.quantity || '';
                if (tUnit) tUnit.value = item.unit || '';
                if (tFood) tFood.value = item.food || '';
            } else {
                const newRow = createIngredientRow(item.quantity || '', item.unit || '', item.food || '');
                if (prevRow.nextElementSibling) {
                    ingredientsList.insertBefore(newRow, prevRow.nextElementSibling);
                } else {
                    ingredientsList.appendChild(newRow);
                }
                targetRow = newRow;
            }
            prevRow = targetRow;
        }

        // Focus the food input of the primary row or next empty row
        if (foodInput) foodInput.focus();
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

        // Intercept paste on any ingredient input box
        ingredientsList.addEventListener('paste', async function (e) {
            const target = e.target;
            if (!target || !target.closest('.ingredient-row')) return;

            const pastedText = (e.clipboardData || window.clipboardData).getData('text');
            if (!pastedText) return;

            const trimmed = pastedText.trim();
            // If the pasted text contains spaces or multiple lines, treat as full ingredient(s)
            if (trimmed.includes('\n') || trimmed.includes(' ')) {
                e.preventDefault();
                const currentRow = target.closest('.ingredient-row');
                const parsed = await parseIngredients(trimmed);
                if (parsed && parsed.length > 0) {
                    applyParsedIngredients(currentRow, parsed);
                } else {
                    target.value = trimmed;
                }
            }
        });

        // Auto-distribute if user types a full line into quantity and tabs/moves away
        ingredientsList.addEventListener('focusout', async function (e) {
            const target = e.target;
            if (target && target.name === 'ingredient_quantity') {
                const val = target.value.trim();
                const isFractionOnly = /^(\d+\s+)?\d+\/\d+$/.test(val);
                if (val.includes(' ') && !isFractionOnly) {
                    const currentRow = target.closest('.ingredient-row');
                    const unitInput = currentRow.querySelector('input[name="ingredient_unit"]');
                    const foodInput = currentRow.querySelector('input[name="ingredient_food"]');
                    if (unitInput && !unitInput.value && foodInput && !foodInput.value) {
                        const parsed = await parseIngredients(val);
                        if (parsed && parsed.length > 0) {
                            applyParsedIngredients(currentRow, parsed);
                        }
                    }
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
