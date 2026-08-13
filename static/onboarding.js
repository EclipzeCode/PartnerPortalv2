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
    contactPhone: document.getElementById('contactPhone'),
    websiteUrl: document.getElementById('websiteUrl'),
    instagramUrl: document.getElementById('instagramUrl'),
    xUrl: document.getElementById('xUrl'),
    linkedinUrl: document.getElementById('linkedinUrl'),
    linksPublic: document.getElementById('linksPublic')
  };

  // Link inputs, keyed by the column name the server uses. Lets a server-side
  // LinkError -- which reports `field` as the column name -- be pointed at the
  // right input without a second mapping to keep in step.
  const LINK_INPUTS = {
    website_url: fields.websiteUrl,
    instagram_url: fields.instagramUrl,
    x_url: fields.xUrl,
    linkedin_url: fields.linkedinUrl
  };

  // `hosts` is the set a URL-shaped value must be on. Absent for the website
  // field, which is any site by definition.
  const LINK_CHECKS = [
    { input: fields.websiteUrl, label: 'Website' },
    { input: fields.instagramUrl, label: 'Instagram', hosts: ['instagram.com'] },
    { input: fields.xUrl, label: 'X', hosts: ['x.com', 'twitter.com'] },
    { input: fields.linkedinUrl, label: 'LinkedIn', hosts: ['linkedin.com'] }
  ];

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
  // Both pickers start as empty bordered boxes about 3rem tall and become
  // scroll containers capped at 18.75rem once the vocabulary arrives -- two
  // of them, so the form below jumped by most of a screen. Placeholder chips
  // hold that space and say the control is a set of things to pick from,
  // which an empty box does not.
  function renderPickerSkeletons() {
    // Group sizes roughly match the real vocabulary, so the height the
    // skeleton reserves is close to the height the chips actually need.
    const html = [6, 5, 7].map((chips) => `
      <div class="category-group">
        <div class="skeleton skeleton-group-heading"></div>
        <div class="category-options">
          ${Array.from({ length: chips },
                       () => '<span class="skeleton skeleton-chip"></span>').join('')}
        </div>
      </div>
    `).join('');

    Object.values(pickers).forEach((container) => {
      container.setAttribute('aria-busy', 'true');
      container.innerHTML = html;
    });
  }

  function clearPickerSkeletons() {
    Object.values(pickers).forEach((container) => {
      container.removeAttribute('aria-busy');
    });
  }

  async function buildPickers(request) {
    renderPickerSkeletons();
    let data;
    try {
      data = await request;
    } catch (err) {
      // Leave the boxes empty rather than shimmering: the error above says
      // what happened, and shimmer that never resolves reads as a page still
      // working on it.
      clearPickerSkeletons();
      Object.values(pickers).forEach((container) => { container.innerHTML = ''; });
      showError('Could not load the category list. Please refresh.');
      throw err;
    }
    clearPickerSkeletons();

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
        const note = container.closest('.form-group').querySelector(':scope > .field-error');
        if (note) note.remove();
        updateProgress();
      });
    });
  }

  // ---- Prefill ----------------------------------------------------------
  // Editing an existing profile should show what is already there rather than
  // making the user retype everything.
  async function prefill(request) {
    let me;
    try {
      me = (await request).organization;
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
    // Stored canonical, so what comes back is what was saved, not what was
    // originally typed -- "@acme" reappears as https://instagram.com/acme.
    if (me.website_url) fields.websiteUrl.value = me.website_url;
    if (me.instagram_url) fields.instagramUrl.value = me.instagram_url;
    if (me.x_url) fields.xUrl.value = me.x_url;
    if (me.linkedin_url) fields.linkedinUrl.value = me.linkedin_url;
    fields.linksPublic.checked = Boolean(me.links_public);
    updateLinksVisibilityNote();

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

    // The heading ships empty; this is the first point at which we know
    // whether the visitor is setting a profile up or coming back to change
    // one. Same signal the submit button already uses. The tab title carries
    // the same static "Get Started" from the <title> tag, so it needs the
    // same fix -- otherwise the tab still announces onboarding while editing.
    const heading = document.getElementById('onboardingTitle');
    if (heading) {
      heading.innerHTML = me.onboarding_complete
        ? `Edit <span>Profile</span>`
        : `Get <span>Started</span>`;
    }
    document.title = me.onboarding_complete
      ? 'Partner Portal | Edit Profile'
      : 'Partner Portal | Get Started';

    if (me.onboarding_complete) {
      submitBtn.innerHTML = `<i class='bx bx-save'></i> Update profile`;
    }
  }

  // ---- Validation -------------------------------------------------------
  // Rules live here rather than on `required` attributes so the messages are
  // ours: the native bubble says "Please fill out this field" and vanishes on
  // the next click, which is no help when several things are wrong at once.
  // Minimums exist because a single character passes a presence check while
  // telling a prospective partner nothing.
  const RULES = {
    organizationName: {
      min: 2,
      label: 'Organization name',
      short: 'Give your full organization name (at least 2 characters).'
    },
    organizationType: {
      min: 1,
      label: 'Organization type',
      short: 'Choose the option that best describes you.'
    },
    location: {
      min: 2,
      label: 'Location',
      short: 'Add a city or region so nearby partners can find you.'
    },
    description: {
      min: 20,
      optional: true,
      label: 'Short description',
      short: 'A description this short will not tell anyone much — aim for a sentence or two.'
    },
    contactEmail: {
      optional: true,
      pattern: /^[^\s@]+@[^\s@]+\.[^\s@]+$/,
      label: 'Contact email',
      short: 'That does not look like an email address.'
    }
  };

  function setFieldError(el, message) {
    if (!el) return;
    el.classList.toggle('input-error', Boolean(message));
    const holder = el.closest('.form-group') || el.parentElement;
    let note = holder.querySelector(':scope > .field-error');
    if (!message) {
      if (note) note.remove();
      return;
    }
    if (!note) {
      note = document.createElement('span');
      note.className = 'field-error';
      holder.appendChild(note);
    }
    note.textContent = message;
  }

  function clearAllFieldErrors() {
    document.querySelectorAll('.field-error').forEach((n) => n.remove());
    Object.values(fields).forEach((f) => f && f.classList.remove('input-error'));
    Object.values(pickers).forEach((p) => p && p.classList.remove('input-error'));
  }

  function validateForm() {
    clearAllFieldErrors();
    clearMessages();

    let firstInvalid = null;
    const problems = [];

    Object.entries(RULES).forEach(([key, rule]) => {
      const field = fields[key];
      if (!field) return;
      const value = String(valueOf(field) || '').trim();

      // Optional fields only get checked once the user has put something in.
      if (rule.optional && value === '') return;

      let message = null;
      if (value === '') {
        message = `${rule.label} is required. ${rule.short}`;
      } else if (rule.min && value.length < rule.min) {
        message = rule.short;
      } else if (rule.pattern && !rule.pattern.test(value)) {
        message = rule.short;
      }

      if (message) {
        setFieldError(field, message);
        problems.push(rule.label);
        if (!firstInvalid) firstInvalid = field;
      }
    });

    // Links: a light pass only, to catch an obvious typo without a round
    // trip. links.py is the authority -- it does the scheme allowlisting and
    // host checking that actually matter, and duplicating that parser here
    // would be two implementations of one security rule, free to drift.
    // Anything this misses comes back from the server pointed at the field.
    LINK_CHECKS.forEach(({ input, label, hosts }) => {
      if (!input) return;
      const value = input.value.trim();
      if (!value) return;  // all four are optional

      let message = null;
      if (/\s/.test(value)) {
        message = `${label}: links cannot contain spaces.`;
      } else {
        const scheme = value.match(/^([A-Za-z][A-Za-z0-9+.-]*):/);
        if (scheme && !/^https?$/i.test(scheme[1])) {
          message = `${label}: links must start with http:// or https://.`;
        } else if (hosts && /[./]/.test(value)) {
          // Looks like a URL rather than a bare handle, so it should be on
          // one of that network's own domains.
          const host = value.replace(/^https?:\/\//i, '').split('/')[0]
            .replace(/^www\./i, '').toLowerCase();
          const ok = hosts.some((h) => host === h || host.endsWith('.' + h));
          if (!ok) message = `${label}: that link is not on ${hosts.join(' or ')}.`;
        }
      }

      if (message) {
        setFieldError(input, message);
        problems.push(label);
        if (!firstInvalid) firstInvalid = input;
      }
    });

    ['needs', 'offers'].forEach((side) => {
      if (selected[side].size > 0) return;
      const picker = pickers[side];
      picker.classList.add('input-error');
      const holder = picker.closest('.form-group');
      let note = holder.querySelector(':scope > .field-error');
      if (!note) {
        note = document.createElement('span');
        note.className = 'field-error';
        holder.appendChild(note);
      }
      note.textContent = side === 'needs'
        ? 'Pick at least one thing you need — this is half of every match.'
        : 'Pick at least one thing you can offer — this is the other half.';
      problems.push(side === 'needs' ? 'What you need' : 'What you offer');
      if (!firstInvalid) firstInvalid = picker;
    });

    if (firstInvalid) {
      showError(
        problems.length === 1
          ? `${problems[0]} still needs attention.`
          : `${problems.length} things still need attention: ${problems.join(', ')}.`
      );
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
      contact_phone: fields.contactPhone.value.trim(),
      website_url: fields.websiteUrl.value.trim(),
      instagram_url: fields.instagramUrl.value.trim(),
      x_url: fields.xUrl.value.trim(),
      linkedin_url: fields.linkedinUrl.value.trim(),
      links_public: fields.linksPublic.checked
    };
  }

  // Says plainly who will see the links, so the choice does not rest on
  // guessing what "everyone" covers.
  function updateLinksVisibilityNote() {
    const note = document.getElementById('linksVisibilityNote');
    if (!note) return;
    note.textContent = fields.linksPublic.checked
      ? 'Anyone who opens your profile page will see them, including people without an account.'
      : 'Only signed-in organizations will see them. Your contact email and phone stay private either way.';
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
      // A rejected link comes back naming the column that failed; point at
      // that input rather than leaving a message at the top of a long form
      // with no indication of which of the four it means.
      const field = error.data && error.data.field;
      const input = field && LINK_INPUTS[field];
      if (input) {
        setFieldError(input, error.message);
        input.scrollIntoView({ behavior: 'smooth', block: 'center' });
        input.focus({ preventScroll: true });
      }
      showError(error.message || 'Something went wrong. Please try again.');
      if (!input) errorMessage.scrollIntoView({ behavior: 'smooth', block: 'center' });
      setLoadingState(false);
    }
  });

  // ---- Clear, behind a confirmation ------------------------------------
  // Losing 30-odd category selections to a stray click is not recoverable,
  // so this asks first.
  const clearModal = document.getElementById('clearConfirmModal');

  function openClearModal() {
    clearModal.classList.add('active');
    document.body.style.overflow = 'hidden';
  }

  function closeClearModal() {
    clearModal.classList.remove('active');
    document.body.style.overflow = 'auto';
  }

  function doClear() {
    onboardingForm.reset();
    Object.values(selected).forEach((set) => set.clear());
    document.querySelectorAll('.category-chip.checked')
      .forEach((c) => c.classList.remove('checked'));
    clearAllFieldErrors();
    clearMessages();
    updateProgress();
    updateLinksVisibilityNote();
  }

  clearBtn.addEventListener('click', openClearModal);
  document.getElementById('clearCancelBtn').addEventListener('click', closeClearModal);
  clearModal.querySelector('.close-modal').addEventListener('click', closeClearModal);
  clearModal.addEventListener('click', (e) => {
    if (e.target === clearModal) closeClearModal();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && clearModal.classList.contains('active')) closeClearModal();
  });
  document.getElementById('clearConfirmBtn').addEventListener('click', () => {
    doClear();
    closeClearModal();
  });

  Object.entries(fields).forEach(([, field]) => {
    if (!field) return;
    const handler = () => {
      // Clear this field's error as soon as the user starts fixing it, rather
      // than leaving stale red text under a field they are already correcting.
      setFieldError(field, null);
      updateProgress();
    };
    field.addEventListener('input', handler);
    field.addEventListener('change', handler);
  });

  fields.linksPublic.addEventListener('change', updateLinksVisibilityNote);
  updateLinksVisibilityNote();

  // Both requests go out now, rather than /api/me waiting for
  // /api/categories to come back first -- the page used to sit through two
  // round trips in series for two calls that have nothing to say to each
  // other. The *awaits* stay ordered, because prefill ticks category
  // checkboxes that buildPickers has to have created first; only the waiting
  // overlaps.
  const categoriesRequest = window.api('/api/categories');
  const meRequest = window.api('/api/me');
  // If categories fails, buildPickers rethrows and the prefill await below is
  // never reached -- leaving meRequest rejected with nothing attached, which
  // the browser reports as an unhandled rejection. Attaching a no-op handler
  // marks it as handled; awaiting it later still sees the real rejection.
  meRequest.catch(() => {});

  await buildPickers(categoriesRequest);
  await prefill(meRequest);
  updateProgress();
});
