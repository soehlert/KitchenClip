document.addEventListener('DOMContentLoaded', () => {
    const handle = document.getElementById('sidebar-handle');
    const overlay = document.getElementById('sidebar-overlay');
    const backdrop = document.getElementById('overlay-backdrop');
    const close = document.getElementById('close-sidebar');

    const open = () => { overlay.classList.add('open'); backdrop.classList.add('show'); handle.style.display = 'none'; };
    const hide = () => { overlay.classList.remove('open'); backdrop.classList.remove('show'); handle.style.display = 'flex'; };

    if (handle) handle.addEventListener('click', open);
    if (close) close.addEventListener('click', hide);
    if (backdrop) backdrop.addEventListener('click', hide);

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

    document.addEventListener('dragstart', e => {
        if (e.target.classList.contains('recipe-card')) {
            dragged = { id: e.target.dataset.id, title: e.target.dataset.title, image: e.target.dataset.image, type: 'recipe' };
            setTimeout(hide, 0);
        } else if (e.target.classList.contains('draggable-meal')) {
            dragged = { id: e.target.dataset.recipeId, title: e.target.querySelector('span').innerText.trim(), image: e.target.querySelector('img')?.src || '', type: e.target.dataset.recipeId ? 'recipe' : 'custom', custom: e.target.dataset.custom, original: e.target.parentElement, ready_at: e.target.querySelector('.ready-at-input').value };
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
            // Snapshot the source slot HTML before clearing it so we can roll back both sides
            const originalSourceHtml = dragged.original ? dragged.original.innerHTML : null;
            updateUI(slot, dragged);
            if (dragged.original) dragged.original.innerHTML = '';

            try {
                const res = await save(date, type, dragged.type === 'recipe' ? dragged.id : null, dragged.type === 'custom' ? dragged.title : '');
                if (!res.ok) throw 'fail';
                if (dragged.original) await save(dragged.original.dataset.date, dragged.original.dataset.type, null, '', 'delete');
            } catch (e) {
                // Roll back both the drop target and the source slot
                slot.innerHTML = originalHtml;
                if (dragged.original && originalSourceHtml !== null) dragged.original.innerHTML = originalSourceHtml;
            }
            dragged = null;
        });
    });

    const modal = document.getElementById('manual-modal');
    const manualText = document.getElementById('manual-text');
    let currentSlot = null;

    const addManualBtn = document.getElementById('add-manual');
    if (addManualBtn) {
        addManualBtn.addEventListener('click', () => {
            currentSlot = document.querySelector('.meal-slot:empty') || slots[0];
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
            const originalHtml = currentSlot.innerHTML;
            updateUI(currentSlot, { type: 'custom', title: title, image: '' });
            modal.classList.add('hidden');
            manualText.value = '';
            hide();
            try {
                const res = await save(currentSlot.dataset.date, currentSlot.dataset.type, null, title);
                if (!res.ok) throw 'fail';
            } catch (e) {
                currentSlot.innerHTML = originalHtml;
            }
        });
    }

    const searchInput = document.getElementById('recipe-search');
    let searchTimeout;
    if (searchInput) {
        const performSearch = async (query) => {
            const response = await fetch(`/api/recipes/search/?q=${encodeURIComponent(query)}`);
            const data = await response.json();
            document.getElementById('sidebar-results').innerHTML = `<h4 class="sidebar-header" style="margin-top:0">Search Results</h4><div class="space-y-2">${data.recipes.map(r => {
                const img = r.image_url ? `<img src="${r.image_url}" class="w-10 h-10 rounded-lg object-cover">` : `<div class="w-10 h-10 rounded-lg bg-gray-200 flex items-center justify-center text-[10px] font-black">${r.title.charAt(0)}</div>`;
                return `<div class="recipe-card p-2 bg-gray-50 rounded-xl flex items-center gap-3 cursor-grab hover:bg-white border border-transparent hover:border-gray-100 transition-all group" draggable="true" data-id="${r.id}" data-title="${r.title}" data-image="${r.image_url || ''}">${img}<span class="font-bold text-gray-700 text-xs truncate">${r.title}</span></div>`;
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
        const img = item.image ? `<img src="${item.image}" class="w-full h-12 object-cover rounded-lg mb-1">` : '';
        const time = item.ready_at || '';
        slot.innerHTML = `<div class="draggable-meal bg-white border border-gray-100 shadow-sm p-2 rounded-xl relative group" draggable="true" data-recipe-id="${item.id || ''}" data-custom="${item.type === 'custom' ? item.title : ''}">${img}<div class="flex justify-between items-center mb-1"><span class="text-[10px] font-bold text-gray-800 leading-tight">${item.title}</span><button class="remove-meal opacity-0 group-hover:opacity-100 text-gray-300 hover:text-red-500 font-bold">&times;</button></div><div class="mt-2 pt-2 border-t border-gray-50 flex justify-end"><div class="time-wrapper relative flex items-center bg-gray-50 hover:bg-gray-100 transition-colors rounded-lg border border-gray-200 px-3 py-1.5 focus-within:ring-1 focus-within:ring-[#194769] focus-within:border-[#194769] cursor-pointer"><span class="text-[9px] font-bold text-gray-400 mr-1 uppercase pointer-events-none">Ready</span><input type="text" class="ready-at-input text-[10px] font-black text-[#194769] bg-transparent border-none p-0 focus:ring-0 cursor-pointer w-20" value="${time}"></div></div></div>`;
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

        if (e.target.closest('.remove-meal')) {
            const meal = e.target.closest('.draggable-meal');
            const slot = meal.parentElement;
            slot.innerHTML = '';
            await save(slot.dataset.date, slot.dataset.type, null, '', 'delete');
            return;
        }

        if (e.target.closest('.ready-at-input') || e.target.closest('.time-wrapper') ||
            e.target.closest('.flatpickr-calendar') || e.target.closest('.sidebar-page-btn') ||
            e.target.closest('.remove-from-menu')) {
            return;
        }

        const toggleMenuBtn = e.target.closest('.toggle-menu-btn');
        if (toggleMenuBtn) {
            const observer = new MutationObserver((mutations) => {
                mutations.forEach((mutation) => {
                    if (mutation.attributeName === "disabled" && !toggleMenuBtn.disabled) {
                        refreshSidebar();
                        observer.disconnect();
                    }
                });
            });
            observer.observe(toggleMenuBtn, { attributes: true });
            return;
        }

        const recipeEl = e.target.closest('.recipe-card') || e.target.closest('.draggable-meal');
        if (recipeEl && !e.target.closest('.remove-meal')) {
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
            hide();
        }
    });
});
