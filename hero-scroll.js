import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js';

const canvas = document.querySelector('.hero-canvas');
const video = document.querySelector('.hero-video-source');
const hero = document.querySelector('.hero');

if (canvas && video && hero && window.innerWidth > 720) {
  video.pause();
  video.currentTime = 0;

  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
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
  let targetTime = 0;
  let displayTime = 0;

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

  // Maps how far the hero has scrolled past the top of the viewport to a point in the video's timeline
  function updateTarget() {
    if (!duration) return;
    const scrubRange = window.innerHeight * 1.4;
    const scrolledPast = THREE.MathUtils.clamp(-hero.getBoundingClientRect().top, 0, scrubRange);
    targetTime = (scrolledPast / scrubRange) * duration;
  }

  function tick() {
    requestAnimationFrame(tick);
    if (!duration) return;

    displayTime += (targetTime - displayTime) * 0.15;
    if (Math.abs(targetTime - displayTime) < 0.008) displayTime = targetTime;

    if (Math.abs(video.currentTime - displayTime) > 0.008) {
      video.currentTime = displayTime;
    }

    renderer.render(scene, camera);
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
  window.addEventListener('resize', () => {
    fitToCanvas();
    updateTarget();
  });

  tick();
}

