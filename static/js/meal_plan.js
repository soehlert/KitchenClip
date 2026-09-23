document.addEventListener('DOMContentLoaded', () => {
    const handle = document.getElementById('sidebar-handle');
    const overlay = document.getElementById('sidebar-overlay');
    const backdrop = document.getElementById('overlay-backdrop');
    const close = document.getElementById('close-sidebar');
    const openLibraryBtn = document.getElementById('open-library-btn');
    const activeSlotBanner = document.getElementById('active-slot-banner');
    const activeSlotLabel = document.getElementById('active-slot-label');
    const cancelActiveSlotBtn = document.getElementById('cancel-active-slot');

    let pendingAction = null; // { type: 'slot_selected'|'place_recipe'|'move_meal', ... }

    const open = () => {
        if (overlay) overlay.classList.add('open');
        if (backdrop) backdrop.classList.add('show');
        if (handle) handle.style.display = 'none';
    };

    const hide = () => {
        if (overlay) overlay.classList.remove('open');
        if (backdrop) backdrop.classList.remove('show');
        if (handle) handle.style.display = 'flex';
        if (pendingAction?.type === 'slot_selected') resetPendingAction();
    };

    function resetPendingAction() {
        pendingAction = null;
        if (activeSlotBanner) activeSlotBanner.classList.add('hidden');
    }

    if (handle) handle.addEventListener('click', () => { resetPendingAction(); open(); });
    if (close) close.addEventListener('click', hide);
    if (backdrop) backdrop.addEventListener('click', hide);
    if (openLibraryBtn) openLibraryBtn.addEventListener('click', () => { resetPendingAction(); open(); });

    if (cancelActiveSlotBtn) {
        cancelActiveSlotBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            resetPendingAction();
        });
    }

    function showToast(msg) {
        const container = document.getElementById('toast-container');
        if (!container) return;
        const toast = document.createElement('div');
        toast.className = 'toast show';
        toast.innerText = msg;
        container.appendChild(toast);
        setTimeout(() => {
            toast.classList.remove('show');
            setTimeout(() => toast.remove(), 300);
        }, 2500);
    }

    const slots = document.querySelectorAll('.meal-slot');
    let dragged = null;

    // Sidebar Pagination and Removal Logic
    const refreshSidebar = async (savedPage = 1, futurePage = 1) => {
        const savedContainer = document.getElementById('section-saved-container');
        const futureContainer = document.getElementById('section-future-container');

        if (savedContainer) savedContainer.classList.add('opacity-50');
        if (futureContainer) futureContainer.classList.add('opacity-50');

        try {
            const res = await fetch(`/api/recipes/sidebar/?saved_page=${savedPage}&future_page=${futurePage}`);
            if (!res.ok) throw new Error('Refresh failed');
            const data = await res.json();

            if (savedContainer) {
                savedContainer.innerHTML = data.saved_html;
                savedContainer.classList.remove('opacity-50');
            }
            if (futureContainer) {
                futureContainer.innerHTML = data.future_html;
                futureContainer.classList.remove('opacity-50');
            }
        } catch (err) {
            console.error("Failed to refresh sidebar", err);
        }
    };

    // Desktop HTML5 Drag & Drop
    document.addEventListener('dragstart', e => {
        if (e.target.classList.contains('recipe-card')) {
            dragged = { id: e.target.dataset.id, title: e.target.dataset.title, image: e.target.dataset.image, type: 'recipe' };
            setTimeout(hide, 0);
        } else if (e.target.classList.contains('draggable-meal')) {
            dragged = {
                id: e.target.dataset.recipeId,
                title: e.target.dataset.title || e.target.querySelector('span')?.innerText.trim() || '',
                image: e.target.querySelector('img')?.src || '',
                type: e.target.dataset.recipeId ? 'recipe' : 'custom',
                custom: e.target.dataset.custom,
                original: e.target.parentElement,
                ready_at: e.target.querySelector('.ready-at-input')?.value || ''
            };
        }
    });

    slots.forEach(slot => {
        slot.addEventListener('dragover', e => { e.preventDefault(); slot.classList.add('drag-over'); });
        slot.addEventListener('dragleave', () => slot.classList.remove('drag-over'));
        slot.addEventListener('drop', async e => {
            e.preventDefault();
            slot.classList.remove('drag-over');
            if (!dragged) return;

            const date = slot.dataset.date;
            const type = slot.dataset.type;

            const originalHtml = slot.innerHTML;
            const originalSourceHtml = dragged.original ? dragged.original.innerHTML : null;
            updateUI(slot, dragged);
            if (dragged.original) {
                dragged.original.innerHTML = `
                    <div class="empty-slot-prompt md:hidden flex items-center justify-center h-full min-h-[70px] text-gray-300 hover:text-gray-400 text-xs font-bold transition-colors">
                        <span class="flex items-center gap-1">+ Add meal</span>
                    </div>
                `;
            }

            try {
                const res = await save(date, type, dragged.type === 'recipe' ? dragged.id : null, dragged.type === 'custom' ? dragged.title : '', 'update', dragged.ready_at || null);
                if (!res.ok) throw 'fail';
                if (dragged.original) await save(dragged.original.dataset.date, dragged.original.dataset.type, null, '', 'delete');
            } catch (err) {
                slot.innerHTML = originalHtml;
                if (dragged.original && originalSourceHtml !== null) dragged.original.innerHTML = originalSourceHtml;
            }
            dragged = null;
        });
    });

    // Custom Meal Modal Logic
    const modal = document.getElementById('manual-modal');
    const manualText = document.getElementById('manual-text');
    let currentCustomSlot = null;

    const addManualBtn = document.getElementById('add-manual');
    if (addManualBtn) {
        addManualBtn.addEventListener('click', () => {
            currentCustomSlot = (pendingAction?.type === 'slot_selected' ? pendingAction.slot : null)
                || document.querySelector('.meal-slot:empty')
                || document.querySelector('.meal-slot:has(.empty-slot-prompt)')
                || slots[0];
            modal.classList.remove('hidden');
            manualText.focus();
        });
    }

    const modalCancelBtn = document.getElementById('modal-cancel');
    if (modalCancelBtn) {
        modalCancelBtn.addEventListener('click', () => {
            modal.classList.add('hidden');
            manualText.value = '';
        });
    }

    const modalSaveBtn = document.getElementById('modal-save');
    if (modalSaveBtn) {
        modalSaveBtn.addEventListener('click', async () => {
            const title = manualText.value.trim();
            if (!title) return;
            const slotToUse = currentCustomSlot || slots[0];
            const originalHtml = slotToUse.innerHTML;
            updateUI(slotToUse, { type: 'custom', title: title, image: '' });
            modal.classList.add('hidden');
            manualText.value = '';
            hide();
            resetPendingAction();
            try {
                const res = await save(slotToUse.dataset.date, slotToUse.dataset.type, null, title);
                if (!res.ok) throw 'fail';
                showToast(`Added ${title} to meal plan`);
            } catch (e) {
                slotToUse.innerHTML = originalHtml;
            }
        });
    }

    // Recipe Search in Sidebar
    const searchInput = document.getElementById('recipe-search');
    let searchTimeout;
    if (searchInput) {
        const performSearch = async (query) => {
            const response = await fetch(`/api/recipes/search/?q=${encodeURIComponent(query)}`);
            const data = await response.json();
            document.getElementById('sidebar-results').innerHTML = `<h4 class="sidebar-header" style="margin-top:0">Search Results</h4><div class="space-y-2">${data.recipes.map(r => {
                const img = r.image_url ? `<img src="${r.image_url}" class="w-10 h-10 rounded-lg object-cover flex-shrink-0">` : `<div class="w-10 h-10 rounded-lg bg-gray-200 flex items-center justify-center text-[10px] font-black flex-shrink-0">${r.title.charAt(0)}</div>`;
                return `<div class="recipe-card p-2 bg-gray-50 rounded-xl flex items-center gap-2 sm:gap-3 cursor-grab hover:bg-white border border-transparent hover:border-gray-100 transition-all group" draggable="true" data-id="${r.id}" data-title="${r.title}" data-image="${r.image_url || ''}">
                    ${img}
                    <span class="font-bold text-gray-700 text-xs truncate flex-1">${r.title}</span>
                </div>`;
            }).join('')}</div>`;
        };

        searchInput.addEventListener('input', () => {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                const query = searchInput.value;
                if (!query) { location.reload(); return; }
                if (query.length < 3) return;
                performSearch(query);
            }, 300);
        });

        searchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                clearTimeout(searchTimeout);
                const query = searchInput.value;
                if (query) performSearch(query);
            }
        });
    }

    const fpConfig = {
        enableTime: true,
        noCalendar: true,
        dateFormat: "H:i",
        time_24hr: false,
        altInput: true,
        altFormat: "h:i K",
        disableMobile: true,
        position: "below center",
        onChange: async function (selectedDates, dateStr, instance) {
            if (!dateStr) return;
            const input = instance.element;
            if (input.classList.contains('ready-at-input')) {
                const meal = input.closest('.draggable-meal');
                if (!meal) return;
                const slot = meal.closest('.meal-slot');
                if (!slot) return;
                input.dataset.manual = 'true';
                const recipeId = meal.dataset.recipeId || null;
                const custom = meal.dataset.custom || '';
                try {
                    await save(slot.dataset.date, slot.dataset.type, recipeId, custom, 'update', dateStr);
                } catch (err) {
                    console.error("Failed to save individual ready_at time", err);
                }
            }
        }
    };

    const globalPickers = {};

    function initTimePickers(container = document) {
        const inputs = container.querySelectorAll('.ready-at-input, #global-lunch, #global-dinner');
        inputs.forEach(input => {
            const instance = flatpickr(input, fpConfig);
            if (input.id === 'global-lunch') globalPickers.lunch = instance;
            if (input.id === 'global-dinner') globalPickers.dinner = instance;
        });
    }

    function getPickerTime(instance) {
        if (!instance) return null;
        if (instance.selectedDates.length) {
            const d = instance.selectedDates[0];
            const h = d.getHours().toString().padStart(2, '0');
            const m = d.getMinutes().toString().padStart(2, '0');
            return `${h}:${m}`;
        }
        return instance.element.value || null;
    }

    initTimePickers();

    function updateUI(slot, item) {
        const img = item.image
            ? `<img src="${item.image}" class="w-full h-12 object-cover rounded-lg mb-1.5">`
            : '';
        const time = item.ready_at || '';
        const title = item.title || '';
        const recipeId = item.id || item.recipeId || '';
        const custom = item.type === 'custom' ? title : (item.custom || '');

        const timeWidget = `
            <div class="mt-1.5 pt-1.5 border-t border-gray-50 flex justify-end">
                <div class="time-wrapper relative flex items-center bg-gray-50 hover:bg-gray-100
                            transition-colors rounded-lg border border-gray-200 px-2 sm:px-3 py-1 sm:py-1.5
                            focus-within:ring-1 focus-within:ring-[#194769] focus-within:border-[#194769]
                            cursor-pointer max-w-full">
                    <span class="text-[8px] sm:text-[9px] font-bold text-gray-400 mr-1 uppercase pointer-events-none">Ready</span>
                    <input type="text"
                           class="ready-at-input text-[10px] font-black text-[#194769] bg-transparent border-none p-0 focus:ring-0 cursor-pointer w-16 sm:w-20"
                           value="${time}">
                </div>
            </div>`;

        slot.innerHTML = `
            <div class="draggable-meal bg-white border border-gray-100 shadow-sm p-2 rounded-xl relative group overflow-hidden max-w-full"
                 draggable="true"
                 data-recipe-id="${recipeId}"
                 data-custom="${custom}"
                 data-title="${title}">
                ${img}
                <div class="flex justify-between items-start gap-1 mb-1">
                    <span class="text-[10px] font-bold text-gray-800 leading-tight flex-1 break-words line-clamp-2">${title}</span>
                    <div class="flex items-center gap-0.5 flex-shrink-0">
                        <button type="button" class="move-meal-btn text-gray-400 hover:text-[#194769] p-1 rounded transition-colors" title="Move meal">
                            <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" />
                            </svg>
                        </button>
                        <button type="button" class="remove-meal text-gray-400 hover:text-red-500 font-bold p-1 leading-none text-sm transition-colors" title="Remove meal">&times;</button>
                    </div>
                </div>
                ${timeWidget}
            </div>`;

        initTimePickers(slot);
    }

    const applyGlobalTimesBtn = document.getElementById('apply-global-times');
    if (applyGlobalTimesBtn) {
        applyGlobalTimesBtn.addEventListener('click', async () => {
            const globalLunch = getPickerTime(globalPickers.lunch);
            const globalDinner = getPickerTime(globalPickers.dinner);
            const filledMeals = document.querySelectorAll('.draggable-meal');
            const originalText = applyGlobalTimesBtn.innerHTML;
            applyGlobalTimesBtn.innerHTML = '<div class="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div> Applying...';
            applyGlobalTimesBtn.disabled = true;

            try {
                for (const meal of filledMeals) {
                    const slot = meal.closest('.meal-slot');
                    if (!slot) continue;
                    const type = slot.dataset.type;
                    const newTime = type === 'LUNCH' ? globalLunch : (type === 'DINNER' ? globalDinner : null);
                    if (newTime) {
                        const input = meal.querySelector('.ready-at-input');
                        if (input?.dataset.manual === 'true') continue;
                        if (input && input._flatpickr) {
                            input._flatpickr.setDate(newTime, false, 'H:i');
                        } else if (input) {
                            input.value = newTime;
                        }
                        const recipeId = meal.dataset.recipeId || null;
                        const custom = meal.dataset.custom || '';
                        await save(slot.dataset.date, type, recipeId, custom, 'update', newTime);
                    }
                }
            } catch (err) {
                console.error("Error saving global times:", err);
            } finally {
                applyGlobalTimesBtn.innerHTML = originalText;
                applyGlobalTimesBtn.disabled = false;
            }
        });
    }

    async function save(date, meal_type, recipe_id, custom_meal = '', action = 'update', ready_at = null) {
        const csrfToken = window.CSRF_TOKEN || '';
        return fetch('/api/meal-plan/update/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
            body: JSON.stringify({ date, meal_type, recipe_id, custom_meal, action, ready_at })
        });
    }

    document.addEventListener('click', async e => {
        // Move Meal button
        const moveBtn = e.target.closest('.move-meal-btn');
        if (moveBtn) {
            e.stopPropagation();
            const meal = moveBtn.closest('.draggable-meal');
            const slot = meal.closest('.meal-slot');
            if (!meal || !slot) return;

            const mealId = meal.dataset.recipeId || null;
            const custom = meal.dataset.custom || '';
            const title = meal.dataset.title || meal.querySelector('span')?.innerText.trim() || '';
            const image = meal.querySelector('img')?.src || '';
            const readyAt = meal.querySelector('.ready-at-input')?.value || '';

            pendingAction = {
                type: 'move_meal',
                sourceSlot: slot,
                sourceDate: slot.dataset.date,
                sourceType: slot.dataset.type,
                mealId,
                custom,
                title,
                image,
                readyAt
            };

            showToast(`Tap any slot to move ${title}`);
            return;
        }

        // Tapping recipe card in sidebar
        const clickedRecipeCard = e.target.closest('.recipe-card');
        if (clickedRecipeCard && !e.target.closest('.remove-from-menu')) {
            e.stopPropagation();
            const id = clickedRecipeCard.dataset.id;
            const title = clickedRecipeCard.dataset.title;
            const image = clickedRecipeCard.dataset.image || '';

            if (pendingAction?.type === 'slot_selected') {
                // Flow 1: Slot was selected first -> place recipe into that slot
                const targetSlot = pendingAction.slot;
                const date = pendingAction.date;
                const type = pendingAction.mealType;
                const label = pendingAction.label;

                updateUI(targetSlot, { id, title, image, type: 'recipe' });
                resetPendingAction();
                hide();
                showToast(`Added ${title} to ${label}`);
                try {
                    await save(date, type, id, '', 'update');
                } catch (err) {
                    console.error("Failed to add recipe to target slot", err);
                }
                return;
            } else {
                // Flow 2: Recipe clicked in sidebar directly -> select it and prompt to tap a slot
                pendingAction = { type: 'place_recipe', id, title, image };
                hide();
                showToast(`Tap any slot to place ${title}`);
                return;
            }
        }

        // Tapping a meal-slot on the calendar
        const clickedSlot = e.target.closest('.meal-slot');
        if (clickedSlot) {
            const destDate = clickedSlot.dataset.date;
            const destType = clickedSlot.dataset.type;
            const dayName = clickedSlot.dataset.dayName || '';
            const dayDate = clickedSlot.dataset.dayDate || '';
            const mealName = destType === 'LUNCH' ? 'Lunch' : 'Dinner';
            const label = `${dayName}${dayDate ? ' (' + dayDate + ')' : ''} ${mealName}`;

            // Case A: Placing a recipe selected from sidebar
            if (pendingAction?.type === 'place_recipe') {
                updateUI(clickedSlot, {
                    id: pendingAction.id,
                    title: pendingAction.title,
                    image: pendingAction.image,
                    type: 'recipe'
                });
                const title = pendingAction.title;
                const recipeId = pendingAction.id;
                resetPendingAction();
                showToast(`Added ${title} to ${label}`);
                try {
                    await save(destDate, destType, recipeId, '', 'update');
                } catch (err) {
                    console.error("Failed to save placed meal", err);
                }
                return;
            }

            // Case B: Moving an existing meal
            if (pendingAction?.type === 'move_meal') {
                if (clickedSlot === pendingAction.sourceSlot) {
                    resetPendingAction();
                    return;
                }

                updateUI(clickedSlot, {
                    id: pendingAction.mealId,
                    title: pendingAction.title,
                    image: pendingAction.image,
                    type: pendingAction.mealId ? 'recipe' : 'custom',
                    ready_at: pendingAction.readyAt
                });

                pendingAction.sourceSlot.innerHTML = `
                    <div class="empty-slot-prompt md:hidden flex items-center justify-center h-full min-h-[70px] text-gray-300 hover:text-gray-400 text-xs font-bold transition-colors">
                        <span class="flex items-center gap-1">+ Add meal</span>
                    </div>
                `;

                const title = pendingAction.title;
                const mealId = pendingAction.mealId;
                const custom = pendingAction.custom;
                const readyAt = pendingAction.readyAt;
                const sourceDate = pendingAction.sourceDate;
                const sourceType = pendingAction.sourceType;

                resetPendingAction();
                showToast(`Moved ${title} to ${label}`);

                try {
                    await save(destDate, destType, mealId, custom, 'update', readyAt || null);
                    await save(sourceDate, sourceType, null, '', 'delete');
                } catch (err) {
                    console.error("Failed to move meal", err);
                }
                return;
            }

            // Case C: Tapping an empty slot -> open Library pre-targeted to this slot
            if (!clickedSlot.querySelector('.draggable-meal')) {
                pendingAction = {
                    type: 'slot_selected',
                    slot: clickedSlot,
                    date: destDate,
                    mealType: destType,
                    label
                };
                if (activeSlotLabel) activeSlotLabel.textContent = label;
                if (activeSlotBanner) activeSlotBanner.classList.remove('hidden');
                open();
                return;
            }
        }

        // Sidebar Pagination
        const pageBtn = e.target.closest('.sidebar-page-btn');
        if (pageBtn) {
            const type = pageBtn.dataset.type;
            const page = pageBtn.dataset.page;
            const otherType = type === 'saved' ? 'future' : 'saved';
            const otherPageSpan = document.querySelector(`#sidebar-section-${otherType} span`);
            const otherPage = otherPageSpan ? otherPageSpan.innerText.replace('Page ', '') : 1;
            if (type === 'saved') {
                refreshSidebar(page, otherPage);
            } else {
                refreshSidebar(otherPage, page);
            }
            return;
        }

        // Remove from Menu (sidebar cross)
        const removeMenuBtn = e.target.closest('.remove-from-menu');
        if (removeMenuBtn) {
            const id = removeMenuBtn.dataset.id;
            try {
                const res = await fetch('/api/recipes/toggle-menu/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': window.CSRF_TOKEN },
                    body: JSON.stringify({ recipe_id: id })
                });
                if (res.ok) refreshSidebar();
            } catch (err) {
                console.error("Failed to remove from menu", err);
            }
            return;
        }

        // Remove meal from slot
        if (e.target.closest('.remove-meal')) {
            const meal = e.target.closest('.draggable-meal');
            const slot = meal.parentElement;
            slot.innerHTML = `
                <div class="empty-slot-prompt md:hidden flex items-center justify-center h-full min-h-[70px] text-gray-300 hover:text-gray-400 text-xs font-bold transition-colors">
                    <span class="flex items-center gap-1">+ Add meal</span>
                </div>
            `;
            await save(slot.dataset.date, slot.dataset.type, null, '', 'delete');
            showToast('Meal removed');
            return;
        }

        if (e.target.closest('.ready-at-input') || e.target.closest('.time-wrapper') ||
            e.target.closest('.flatpickr-calendar') || e.target.closest('.sidebar-page-btn') ||
            e.target.closest('.remove-from-menu') || e.target.closest('.move-meal-btn')) {
            return;
        }

        const toggleMenuBtn = e.target.closest('.toggle-menu-btn');
        if (toggleMenuBtn) {
            toggleMenuBtn.addEventListener('menuToggled', () => refreshSidebar(), { once: true });
            return;
        }

        // Recipe Detail Modal (for recipe card or meal card)
        const recipeEl = e.target.closest('.recipe-card') || e.target.closest('.draggable-meal');
        if (recipeEl && !e.target.closest('.remove-meal') && !e.target.closest('.move-meal-btn')) {
            const id = recipeEl.dataset.id || recipeEl.dataset.recipeId;
            const recipeModal = document.getElementById('recipe-modal');
            const contentContainer = document.getElementById('recipe-modal-content');
            if (recipeModal && contentContainer) {
                if (id) {
                    recipeModal.classList.remove('hidden');
                    contentContainer.innerHTML = `<div class="flex justify-center items-center h-40"><div class="animate-spin rounded-full h-8 w-8 border-b-2 border-[#194769]"></div></div>`;
                    try {
                        const res = await fetch(`/${id}/`);
                        if (!res.ok) throw new Error('Network response was not ok');
                        const text = await res.text();
                        const parser = new DOMParser();
                        const doc = parser.parseFromString(text, 'text/html');
                        const content = doc.querySelector('.max-w-2xl');
                        if (content) {
                            contentContainer.innerHTML = '';
                            contentContainer.appendChild(content);
                            content.classList.remove('mt-8');
                        } else {
                            contentContainer.innerHTML = '<div class="p-8 text-center text-red-500">Could not load recipe details.</div>';
                        }
                    } catch (err) {
                        contentContainer.innerHTML = '<div class="p-8 text-center text-red-500">Error loading recipe.</div>';
                    }
                } else {
                    recipeModal.classList.remove('hidden');
                    contentContainer.innerHTML = '<div class="p-8 text-center text-gray-500 font-bold text-xl mt-12">Custom meals do not have recipe details.</div>';
                }
            }
        }
    });

    const recipeModal = document.getElementById('recipe-modal');
    const closeRecipeModalBtn = document.getElementById('close-recipe-modal');
    if (closeRecipeModalBtn && recipeModal) {
        closeRecipeModalBtn.addEventListener('click', () => { recipeModal.classList.add('hidden'); });
        recipeModal.addEventListener('click', (e) => { if (e.target === recipeModal) recipeModal.classList.add('hidden'); });
    }
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            const modal = document.getElementById('manual-modal');
            const recipeModal = document.getElementById('recipe-modal');
            if (modal && !modal.classList.contains('hidden')) modal.classList.add('hidden');
            if (recipeModal && !recipeModal.classList.contains('hidden')) recipeModal.classList.add('hidden');
            resetPendingAction();
            hide();
        }
    });
});
