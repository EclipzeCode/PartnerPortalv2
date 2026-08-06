document.addEventListener('DOMContentLoaded', () => {
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
    needs: document.getElementById('needs'),
    offers: document.getElementById('offers'),
    preferredPartnerTypes: document.getElementById('preferredPartnerTypes'),
    partnershipGoals: document.getElementById('partnershipGoals'),
    description: document.getElementById('description')
  };

  const requiredFieldKeys = [
    'organizationName',
    'organizationType',
    'location',
    'needs',
    'offers'
  ];

  // Fields tracked by the sidebar checklist / strength meter.
  const trackedKeys = [
    'organizationName',
    'organizationType',
    'location',
    'needs',
    'offers',
    'description'
  ];

  // Which fields belong to which card in the progress strip.
  const stepFields = {
    1: ['organizationName', 'organizationType', 'location'],
    2: ['needs', 'offers'],
    3: ['preferredPartnerTypes', 'partnershipGoals', 'description']
  };

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
      if (field && field.classList) {
        field.classList.remove('input-error');
      }
    });
  }

  function validateForm() {
    clearValidationStyles();
    clearMessages();

    let isValid = true;
    let firstInvalid = null;

    requiredFieldKeys.forEach((key) => {
      const field = fields[key];
      if (!valueOf(field)) {
        field.classList.add('input-error');
        if (!firstInvalid) firstInvalid = field;
        isValid = false;
      }
    });

    if (!isValid) {
      showError('Please fill in all required fields before continuing.');
      // Take the user to the problem rather than leaving them to hunt for it.
      firstInvalid.scrollIntoView({ behavior: 'smooth', block: 'center' });
      firstInvalid.focus({ preventScroll: true });
    }

    return isValid;
  }

  function buildPayload() {
    return {
      organization_name: fields.organizationName.value.trim(),
      organization_type: fields.organizationType.value.trim(),
      location: fields.location.value.trim(),
      remote_friendly: fields.remoteFriendly.checked,
      needs: fields.needs.value.trim(),
      offers: fields.offers.value.trim(),
      preferred_partner_types: fields.preferredPartnerTypes.value.trim(),
      partnership_goals: fields.partnershipGoals.value.trim(),
      description: fields.description.value.trim()
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
    let filled = 0;

    trackedKeys.forEach((key) => {
      const done = Boolean(valueOf(fields[key]));
      if (done) filled += 1;
      const item = checklist.querySelector(`li[data-field="${key}"]`);
      if (item) {
        item.classList.toggle('done', done);
        const icon = item.querySelector('i');
        icon.className = done ? 'bx bx-check-circle' : 'bx bx-circle';
      }
    });

    const pct = Math.round((filled / trackedKeys.length) * 100);
    strengthFill.style.width = pct + '%';

    let label;
    if (pct === 0) label = 'Just getting started';
    else if (pct < 50) label = `${pct}% — keep going`;
    else if (pct < 100) label = `${pct}% — looking good`;
    else label = '100% — ready to match';
    strengthLabel.textContent = label;

    Object.entries(stepFields).forEach(([step, keys]) => {
      const card = document.querySelector(`.progress-step[data-step="${step}"]`);
      if (card) {
        card.classList.toggle('done', keys.every((k) => Boolean(valueOf(fields[k]))));
      }
    });
  }

  function updateCharCount(key) {
    const counter = document.querySelector(`.char-count[data-for="${key}"]`);
    if (!counter) return;
    const len = fields[key].value.trim().length;
    counter.textContent = `${len} character${len === 1 ? '' : 's'}`;
  }

  // ---- Submit -----------------------------------------------------------
  onboardingForm.addEventListener('submit', async (e) => {
    e.preventDefault();

    if (!validateForm()) return;

    const payload = buildPayload();

    try {
      setLoadingState(true);

      const response = await fetch(`${window.API_BASE}/api/onboarding`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Failed to save onboarding profile.');
      }

      localStorage.setItem('partnerPortalOnboardingProfile', JSON.stringify(data.profile));

      showSuccess('Profile saved. Redirecting you to partner matches...');
      successMessage.scrollIntoView({ behavior: 'smooth', block: 'center' });

      setTimeout(() => {
        window.location.href = 'ppsearch.html';
      }, 1200);
    } catch (error) {
      showError(error.message || 'Something went wrong. Please try again.');
      errorMessage.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } finally {
      setLoadingState(false);
    }
  });

  clearBtn.addEventListener('click', () => {
    onboardingForm.reset();
    clearValidationStyles();
    clearMessages();
    updateProgress();
    ['needs', 'offers'].forEach(updateCharCount);
  });

  // ---- Wiring -----------------------------------------------------------
  Object.entries(fields).forEach(([key, field]) => {
    if (!field) return;
    const handler = () => {
      field.classList.remove('input-error');
      updateProgress();
      updateCharCount(key);
    };
    field.addEventListener('input', handler);
    field.addEventListener('change', handler);
  });

  updateProgress();
  ['needs', 'offers'].forEach(updateCharCount);
});
