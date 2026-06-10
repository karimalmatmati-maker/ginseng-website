// Reveal-on-scroll for cards and fade-up elements
const revealEls = document.querySelectorAll('.feature-card, .price-card, .reveal-fade');

const revealObserver = new IntersectionObserver((entries) => {
  entries.forEach((entry) => {
    if (entry.isIntersecting) {
      entry.target.classList.add('in-view');
      revealObserver.unobserve(entry.target);
    }
  });
}, { threshold: 0.15 });

revealEls.forEach((el) => {
  el.classList.add('reveal-fade');
  revealObserver.observe(el);
});

// Animated counters for hero stats
const counters = document.querySelectorAll('.counter');

const formatNumber = (value, decimals) => {
  return decimals
    ? value.toFixed(decimals).replace('.', ',')
    : Math.round(value).toLocaleString('de-DE');
};

const counterObserver = new IntersectionObserver((entries) => {
  entries.forEach((entry) => {
    if (!entry.isIntersecting) return;
    const el = entry.target;
    const target = parseFloat(el.dataset.count);
    const decimals = parseInt(el.dataset.decimals || '0', 10);
    const suffix = el.dataset.suffix || '';
    const duration = 1400;
    const start = performance.now();

    const tick = (now) => {
      const progress = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      el.textContent = formatNumber(target * eased, decimals) + suffix;
      if (progress < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
    counterObserver.unobserve(el);
  });
}, { threshold: 0.6 });

counters.forEach((el) => counterObserver.observe(el));

// Scroll progress bar
const scrollBarFill = document.querySelector('.scroll-bar span');
if (scrollBarFill) {
  const updateScrollBar = () => {
    const scrollable = document.documentElement.scrollHeight - window.innerHeight;
    const progress = scrollable > 0 ? (window.scrollY / scrollable) * 100 : 0;
    scrollBarFill.style.width = progress + '%';
  };
  window.addEventListener('scroll', updateScrollBar, { passive: true });
  window.addEventListener('resize', updateScrollBar);
  updateScrollBar();
}

// Ambient cursor glow that follows the pointer
const cursorGlow = document.querySelector('.cursor-glow');
if (cursorGlow && window.matchMedia('(pointer: fine)').matches) {
  let targetX = window.innerWidth / 2;
  let targetY = window.innerHeight / 2;
  let currentX = targetX;
  let currentY = targetY;

  window.addEventListener('mousemove', (e) => {
    targetX = e.clientX;
    targetY = e.clientY;
    cursorGlow.classList.add('is-active');
  });
  window.addEventListener('mouseleave', () => cursorGlow.classList.remove('is-active'));

  const followCursor = () => {
    currentX += (targetX - currentX) * 0.12;
    currentY += (targetY - currentY) * 0.12;
    cursorGlow.style.transform = `translate(${currentX - 190}px, ${currentY - 190}px)`;
    requestAnimationFrame(followCursor);
  };
  requestAnimationFrame(followCursor);
}

// Magnetic buttons — subtle pull toward the cursor
const magneticEls = document.querySelectorAll('.magnetic');
if (window.matchMedia('(pointer: fine)').matches) {
  magneticEls.forEach((el) => {
    const strength = 0.3;

    el.addEventListener('mousemove', (e) => {
      const rect = el.getBoundingClientRect();
      const relX = e.clientX - rect.left - rect.width / 2;
      const relY = e.clientY - rect.top - rect.height / 2;
      el.style.transform = `translate(${relX * strength}px, ${relY * strength}px)`;
      const inner = el.querySelector('span');
      if (inner) inner.style.transform = `translate(${relX * strength * 0.4}px, ${relY * strength * 0.4}px)`;
    });

    el.addEventListener('mouseleave', () => {
      el.style.transform = '';
      const inner = el.querySelector('span');
      if (inner) inner.style.transform = '';
    });
  });
}
