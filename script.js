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
  // document.documentElement.scrollHeight forces a synchronous layout when
  // the DOM has pending style changes. The page's total height only changes
  // on resize/load, so measure it there and keep the scroll handler down to
  // a single style write (no read-after-write layout thrash on scroll).
  let scrollableHeight = document.documentElement.scrollHeight - window.innerHeight;
  const measureScrollable = () => {
    scrollableHeight = document.documentElement.scrollHeight - window.innerHeight;
  };
  const updateScrollBar = () => {
    const progress = scrollableHeight > 0 ? (window.scrollY / scrollableHeight) * 100 : 0;
    scrollBarFill.style.width = progress + '%';
  };
  window.addEventListener('scroll', updateScrollBar, { passive: true });
  window.addEventListener('resize', () => {
    measureScrollable();
    updateScrollBar();
  });
  window.addEventListener('load', () => {
    measureScrollable();
    updateScrollBar();
  });
  updateScrollBar();
}

// Ambient cursor glow that follows the pointer
const cursorGlow = document.querySelector('.cursor-glow');
if (cursorGlow && window.matchMedia('(pointer: fine)').matches) {
  let targetX = window.innerWidth / 2;
  let targetY = window.innerHeight / 2;
  let currentX = targetX;
  let currentY = targetY;
  let glowLoopRunning = false;

  // A lower factor here means the glow takes longer to catch up to the
  // pointer - it reads as a soft mass drifting through resistance rather
  // than a cursor-locked dot.
  const followCursor = () => {
    currentX += (targetX - currentX) * 0.09;
    currentY += (targetY - currentY) * 0.09;
    cursorGlow.style.transform = `translate(${currentX - 190}px, ${currentY - 190}px)`;

    // Once the glow has caught up with the pointer there is nothing left to
    // animate; stop the rAF loop and let the next mousemove restart it.
    if (Math.abs(targetX - currentX) < 0.05 && Math.abs(targetY - currentY) < 0.05) {
      currentX = targetX;
      currentY = targetY;
      glowLoopRunning = false;
      return;
    }
    requestAnimationFrame(followCursor);
  };

  window.addEventListener('mousemove', (e) => {
    targetX = e.clientX;
    targetY = e.clientY;
    cursorGlow.classList.add('is-active');
    if (!glowLoopRunning) {
      glowLoopRunning = true;
      requestAnimationFrame(followCursor);
    }
  });
  window.addEventListener('mouseleave', () => cursorGlow.classList.remove('is-active'));
}

// Magnetic buttons — subtle pull toward the cursor
const magneticEls = document.querySelectorAll('.magnetic');
if (window.matchMedia('(pointer: fine)').matches) {
  magneticEls.forEach((el) => {
    const strength = 0.3;
    const inner = el.querySelector('span');
    let rect = null;

    // getBoundingClientRect() forces a layout read; the button's size and
    // position don't change while the cursor is over it, so measure once on
    // enter and reuse that rect for every mousemove until the cursor leaves.
    el.addEventListener('mouseenter', () => {
      rect = el.getBoundingClientRect();
    });

    el.addEventListener('mousemove', (e) => {
      if (!rect) rect = el.getBoundingClientRect();
      const relX = e.clientX - rect.left - rect.width / 2;
      const relY = e.clientY - rect.top - rect.height / 2;
      el.style.transform = `translate(${relX * strength}px, ${relY * strength}px)`;
      if (inner) inner.style.transform = `translate(${relX * strength * 0.4}px, ${relY * strength * 0.4}px)`;
    });

    el.addEventListener('mouseleave', () => {
      rect = null;
      el.style.transform = '';
      if (inner) inner.style.transform = '';
    });
  });
}

// In-page navigation: ease into the target section with a slow-fast-slow
// glide whose duration scales with distance, so the page settles into the
// next section rather than snapping straight there (replaces the browser's
// short, generic scroll-behavior: smooth).
const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

function easeInOutCubic(t) {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

document.querySelectorAll('a[href^="#"]').forEach((link) => {
  link.addEventListener('click', (e) => {
    const id = link.getAttribute('href');
    if (id.length < 2) return;
    const target = document.querySelector(id);
    if (!target || prefersReducedMotion) return;

    e.preventDefault();

    const startY = window.scrollY;
    const distance = target.getBoundingClientRect().top;
    const duration = Math.min(1100, Math.max(500, Math.abs(distance) * 0.6));
    const startTime = performance.now();

    function step(now) {
      const t = Math.min((now - startTime) / duration, 1);
      window.scrollTo(0, startY + distance * easeInOutCubic(t));
      if (t < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  });
});
