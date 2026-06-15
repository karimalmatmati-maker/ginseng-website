import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js';

const canvas = document.querySelector('.hero-canvas');
const video = document.querySelector('.hero-video-source');
const hero = document.querySelector('.hero');

if (canvas && video && hero) {
  video.pause();
  video.currentTime = 0;

  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: false, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera();
  camera.position.z = 1;

  const videoTexture = new THREE.VideoTexture(video);
  videoTexture.colorSpace = THREE.SRGBColorSpace;

  const plane = new THREE.Mesh(
    new THREE.PlaneGeometry(1, 1),
    new THREE.MeshBasicMaterial({ map: videoTexture })
  );
  scene.add(plane);

  let duration = 0;
  let targetProgress = 0;
  let currentProgress = 0;

  // The scene is static almost all of the time (no scrolling, easing
  // settled, no pending seek), so most rAF frames have nothing new to
  // paint. renderCooldown counts down the remaining frames that still need
  // a render(); bumpRender() is called whenever scroll, easing, or a video
  // seek actually changes the picture.
  let renderCooldown = 3;
  function bumpRender(frames = 2) {
    renderCooldown = Math.max(renderCooldown, frames);
  }

  // Orthographic frustum sized in CSS pixels, plane scaled to crop like object-fit: cover
  function fitToCanvas() {
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (!width || !height) return;

    renderer.setSize(width, height, false);

    camera.left = -width / 2;
    camera.right = width / 2;
    camera.top = height / 2;
    camera.bottom = -height / 2;
    camera.near = 0.1;
    camera.far = 10;
    camera.updateProjectionMatrix();

    const videoAspect = (video.videoWidth || 16) / (video.videoHeight || 9);
    const canvasAspect = width / height;

    if (videoAspect > canvasAspect) {
      plane.scale.set(height * videoAspect, height, 1);
    } else {
      plane.scale.set(width, width / videoAspect, 1);
    }
  }

  // Single smooth S-curve: zero first AND second derivative at both ends and
  // no piecewise midpoint (unlike easeInOutCubic), so the reveal eases in
  // and out without any perceptible kink
  function smootherstep(x) {
    return x * x * x * (x * (x * 6 - 15) + 10);
  }

  // Desktop: the hero is pinned (position: sticky) for its own height minus
  // one viewport; that whole range maps directly to a 0-1 scroll progress target.
  // Mobile: the visual panel sits in normal page flow (no sticky pin), so
  // progress instead follows the panel's own position as it scrolls through
  // the viewport - this stays in sync with touch/swipe scrolling and is
  // immune to mobile browsers resizing the viewport as the address bar hides.
  // Lower = more lag between scroll input and the jar's response, reading
  // as more inertia/mass rather than a label tracking the scrollbar 1:1.
  const SMOOTHING = 0.065;

  function updateTarget() {
    if (!duration) return;

    const previous = targetProgress;

    if (window.innerWidth > 720) {
      const scrubRange = hero.offsetHeight - window.innerHeight;
      const scrolled = scrubRange > 0
        ? THREE.MathUtils.clamp(window.scrollY, 0, scrubRange)
        : 0;
      targetProgress = scrubRange > 0 ? scrolled / scrubRange : 0;
    } else {
      const rect = canvas.getBoundingClientRect();
      const scrubRange = rect.height;
      const scrolled = scrubRange > 0
        ? THREE.MathUtils.clamp(-rect.top + rect.height * 0.5, 0, scrubRange)
        : 0;
      targetProgress = scrubRange > 0 ? scrolled / scrubRange : 0;
    }

    if (Math.abs(targetProgress - previous) > 0.0001) bumpRender();
  }

  // Setting video.currentTime triggers an async decode (seeking -> seeked).
  // Issuing a new seek before the previous one resolves causes the browser
  // to abandon it, so a rapid stream of currentTime writes can leave the
  // decoded frame (and the texture) stuck for long stretches. Pacing writes
  // to one in-flight seek at a time guarantees every seek lands on a frame.
  let seekPending = false;
  let seekStartedAt = 0;
  const SEEK_TIMEOUT = 200;
  let hasFirstFrame = false;

  video.addEventListener('seeked', () => {
    seekPending = false;
    bumpRender(2); // give the freshly decoded frame a couple of frames to land in the texture
  });

  function tick() {
    requestAnimationFrame(tick);
    if (!duration) return;

    // currentProgress eases toward targetProgress every frame, giving the
    // jar a slight, springy "follow" lag instead of snapping straight to the
    // scroll position; smootherstep then shapes that smoothed progress into time
    const previousProgress = currentProgress;
    currentProgress += (targetProgress - currentProgress) * SMOOTHING;
    if (Math.abs(targetProgress - currentProgress) < 0.0006) currentProgress = targetProgress;
    if (currentProgress !== previousProgress) bumpRender();

    const time = smootherstep(currentProgress) * duration;

    if (seekPending && performance.now() - seekStartedAt > SEEK_TIMEOUT) {
      seekPending = false; // safety net if 'seeked' never fires
    }

    if (!seekPending && Math.abs(video.currentTime - time) > 0.003) {
      seekPending = true;
      seekStartedAt = performance.now();
      video.currentTime = time;
      bumpRender(2);
    }

    // The first decoded video frame needs one extra render once it becomes
    // available, even if scroll progress hasn't changed since page load.
    if (!hasFirstFrame && video.readyState >= 2) {
      hasFirstFrame = true;
      bumpRender(2);
    }

    if (renderCooldown > 0 || seekPending) {
      renderer.render(scene, camera);
      if (renderCooldown > 0) renderCooldown--;
    }
  }

  function onMetadataReady() {
    duration = video.duration;
    fitToCanvas();
    updateTarget();
  }

  // readyState may already be >= HAVE_METADATA before this script attaches
  // its listener (cached video), in which case loadedmetadata never fires here
  if (video.readyState >= 1 && isFinite(video.duration)) {
    onMetadataReady();
  } else {
    video.addEventListener('loadedmetadata', onMetadataReady, { once: true });
  }

  window.addEventListener('scroll', updateTarget, { passive: true });

  // Multiple 'resize' events can fire per frame while a window is being
  // dragged; coalesce them into a single fitToCanvas()/updateTarget() per
  // frame instead of reallocating the WebGL framebuffer repeatedly.
  let resizePending = false;
  window.addEventListener('resize', () => {
    if (resizePending) return;
    resizePending = true;
    requestAnimationFrame(() => {
      resizePending = false;
      fitToCanvas();
      updateTarget();
      bumpRender();
    });
  });

  tick();
}

