document.addEventListener('DOMContentLoaded', async () => {
  const onboardingForm = document.getElementById('onboardingForm');
  const submitBtn = document.getElementById('submitBtn');
  const clearBtn = document.getElementById('clearBtn');

  const successMessage = document.getElementById('successMessage');
  const errorMessage = document.getElementById('errorMessage');

  const strengthFill = document.getElementById('strengthFill');
  const strengthLabel = document.getElementById('strengthLabel');
  const checklist = document.getElementById('checklist');

  const fields = {
    organizationName: document.getElementById('organizationName'),
    organizationType: document.getElementById('organizationType'),
    location: document.getElementById('location'),
    remoteFriendly: document.getElementById('remoteFriendly'),
    needsNote: document.getElementById('needsNote'),
    offersNote: document.getElementById('offersNote'),
    partnershipGoals: document.getElementById('partnershipGoals'),
    description: document.getElementById('description'),
    contactEmail: document.getElementById('contactEmail'),
    contactPhone: document.getElementById('contactPhone')
  };

  const pickers = {
    needs: document.getElementById('needsPicker'),
    offers: document.getElementById('offersPicker')
  };

  // Selected category slugs. These, not the free-text notes, are what matching
  // actually runs on.
  const selected = { needs: new Set(), offers: new Set() };

  const trackedKeys = ['organizationName', 'organizationType', 'location', 'description'];

  function valueOf(field) {
    if (!field) return '';
    return field.type === 'checkbox' ? field.checked : field.value.trim();
  }

  function showSuccess(message) {
    successMessage.textContent = message;
    successMessage.classList.remove('hidden');
    errorMessage.classList.add('hidden');
  }

  function showError(message) {
    errorMessage.textContent = message;
    errorMessage.classList.remove('hidden');
    successMessage.classList.add('hidden');
  }

  function clearMessages() {
    successMessage.classList.add('hidden');
    errorMessage.classList.add('hidden');
  }

  function clearValidationStyles() {
    Object.values(fields).forEach((field) => {
      if (field && field.classList) field.classList.remove('input-error');
    });
    Object.values(pickers).forEach((p) => p && p.classList.remove('input-error'));
  }

  // ---- Category pickers -------------------------------------------------
  async function buildPickers() {
    let data;
    try {
      data = await window.api('/api/categories');
    } catch (err) {
      showError('Could not load the category list. Please refresh.');
      throw err;
    }

    // Organization types come from the same endpoint so the values stored
    // here match what every other organization is stored with.
    const typeSelect = fields.organizationType;
    data.organization_types.forEach((type) => {
      const opt = document.createElement('option');
      opt.value = type;
      opt.textContent = type;
      typeSelect.appendChild(opt);
    });

    Object.entries(pickers).forEach(([side, container]) => {
      container.innerHTML = '';
      data.groups.forEach((group) => {
        const wrap = document.createElement('div');
        wrap.className = 'category-group';

        const heading = document.createElement('h4');
        heading.textContent = group.name;
        wrap.appendChild(heading);

        const list = document.createElement('div');
        list.className = 'category-options';

        group.categories.forEach((cat) => {
          const id = `${side}-${cat.slug}`;
          const label = document.createElement('label');
          label.className = 'category-chip';
          label.setAttribute('for', id);
          label.innerHTML = `
            <input type="checkbox" id="${id}" value="${window.escapeHtml(cat.slug)}">
            <span>${window.escapeHtml(cat.label)}</span>
          `;
          list.appendChild(label);
        });

        wrap.appendChild(list);
        container.appendChild(wrap);
      });

      container.addEventListener('change', (e) => {
        const box = e.target.closest('input[type="checkbox"]');
        if (!box) return;
        if (box.checked) selected[side].add(box.value);
        else selected[side].delete(box.value);
        box.closest('.category-chip').classList.toggle('checked', box.checked);
        container.classList.remove('input-error');
        updateProgress();
      });
    });
  }

  // ---- Prefill ----------------------------------------------------------
  // Editing an existing profile should show what is already there rather than
  // making the user retype everything.
  async function prefill() {
    let me;
    try {
      me = (await window.api('/api/me')).organization;
    } catch {
      return; // api() already redirected to login on a 401
    }

    if (me.name) fields.organizationName.value = me.name;
    if (me.organization_type) fields.organizationType.value = me.organization_type;
    if (me.location) fields.location.value = me.location;
    fields.remoteFriendly.checked = Boolean(me.remote_friendly);
    if (me.needs_note) fields.needsNote.value = me.needs_note;
    if (me.offers_note) fields.offersNote.value = me.offers_note;
    if (me.partnership_goals) fields.partnershipGoals.value = me.partnership_goals;
    if (me.description) fields.description.value = me.description;
    if (me.contact_email) fields.contactEmail.value = me.contact_email;
    if (me.contact_phone) fields.contactPhone.value = me.contact_phone;

    [['needs', me.needs], ['offers', me.offers]].forEach(([side, slugs]) => {
      (slugs || []).forEach((slug) => {
        const box = document.getElementById(`${side}-${slug}`);
        if (box) {
          box.checked = true;
          box.closest('.category-chip').classList.add('checked');
          selected[side].add(slug);
        }
      });
    });

    if (me.onboarding_complete) {
      submitBtn.innerHTML = `<i class='bx bx-save'></i> Update profile`;
    }
  }

  // ---- Validation -------------------------------------------------------
  function validateForm() {
    clearValidationStyles();
    clearMessages();

    let firstInvalid = null;

    ['organizationName', 'organizationType', 'location'].forEach((key) => {
      const field = fields[key];
      if (!valueOf(field)) {
        field.classList.add('input-error');
        if (!firstInvalid) firstInvalid = field;
      }
    });

    ['needs', 'offers'].forEach((side) => {
      if (selected[side].size === 0) {
        pickers[side].classList.add('input-error');
        if (!firstInvalid) firstInvalid = pickers[side];
      }
    });

    if (firstInvalid) {
      showError('Pick at least one need and one offer, and fill in the required fields.');
      firstInvalid.scrollIntoView({ behavior: 'smooth', block: 'center' });
      if (firstInvalid.focus) firstInvalid.focus({ preventScroll: true });
      return false;
    }
    return true;
  }

  function buildPayload() {
    return {
      organization_name: fields.organizationName.value.trim(),
      organization_type: fields.organizationType.value.trim(),
      location: fields.location.value.trim(),
      remote_friendly: fields.remoteFriendly.checked,
      needs: [...selected.needs],
      offers: [...selected.offers],
      needs_note: fields.needsNote.value.trim(),
      offers_note: fields.offersNote.value.trim(),
      partnership_goals: fields.partnershipGoals.value.trim(),
      description: fields.description.value.trim(),
      contact_email: fields.contactEmail.value.trim(),
      contact_phone: fields.contactPhone.value.trim()
    };
  }

  function setLoadingState(isLoading) {
    submitBtn.disabled = isLoading;
    submitBtn.innerHTML = isLoading
      ? `<i class='bx bx-loader-alt bx-spin'></i> Saving...`
      : `<i class='bx bx-search-alt-2'></i> Save &amp; Find Matches`;
  }

  // ---- Live sidebar feedback -------------------------------------------
  function updateProgress() {
    const done = {
      organizationName: Boolean(valueOf(fields.organizationName)),
      organizationType: Boolean(valueOf(fields.organizationType)),
      location: Boolean(valueOf(fields.location)),
      needs: selected.needs.size > 0,
      offers: selected.offers.size > 0,
      description: Boolean(valueOf(fields.description))
    };

    Object.entries(done).forEach(([key, isDone]) => {
      const item = checklist.querySelector(`li[data-field="${key}"]`);
      if (!item) return;
      item.classList.toggle('done', isDone);
      const icon = item.querySelector('i');
      icon.className = isDone ? 'bx bx-check-circle' : 'bx bx-circle';
    });

    const total = Object.keys(done).length;
    const filled = Object.values(done).filter(Boolean).length;
    const pct = Math.round((filled / total) * 100);
    strengthFill.style.width = pct + '%';

    let label;
    if (pct === 0) label = 'Just getting started';
    else if (pct < 50) label = `${pct}% — keep going`;
    else if (pct < 100) label = `${pct}% — looking good`;
    else label = '100% — ready to match';
    strengthLabel.textContent = label;

    ['needs', 'offers'].forEach((side) => {
      const counter = document.querySelector(`.picker-count[data-for="${side}"]`);
      if (!counter) return;
      const n = selected[side].size;
      counter.textContent = n === 0 ? 'None selected' : `${n} selected`;
    });

    const steps = {
      1: done.organizationName && done.organizationType && done.location,
      2: done.needs && done.offers,
      3: done.description
    };
    Object.entries(steps).forEach(([step, isDone]) => {
      const card = document.querySelector(`.progress-step[data-step="${step}"]`);
      if (card) card.classList.toggle('done', isDone);
    });
  }

  // ---- Submit -----------------------------------------------------------
  onboardingForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!validateForm()) return;

    try {
      setLoadingState(true);
      await window.api('/api/onboarding', {
        method: 'POST',
        body: buildPayload()
      });

      showSuccess('Profile saved. Finding your matches...');
      successMessage.scrollIntoView({ behavior: 'smooth', block: 'center' });
      setTimeout(() => { window.location.href = 'ppsearch.html'; }, 900);
    } catch (error) {
      showError(error.message || 'Something went wrong. Please try again.');
      errorMessage.scrollIntoView({ behavior: 'smooth', block: 'center' });
      setLoadingState(false);
    }
  });

  clearBtn.addEventListener('click', () => {
    onboardingForm.reset();
    Object.values(selected).forEach((set) => set.clear());
    document.querySelectorAll('.category-chip.checked')
      .forEach((c) => c.classList.remove('checked'));
    clearValidationStyles();
    clearMessages();
    updateProgress();
  });

  Object.entries(fields).forEach(([, field]) => {
    if (!field) return;
    const handler = () => {
      field.classList.remove('input-error');
      updateProgress();
    };
    field.addEventListener('input', handler);
    field.addEventListener('change', handler);
  });

  await buildPickers();
  await prefill();
  updateProgress();
});
