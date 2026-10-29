(() => {
  const carousel = document.querySelector('[data-student-events-carousel]');
  if (!carousel) return;

  const track = carousel.querySelector('[data-carousel-track]');
  const slides = [...track.children];
  if (slides.length < 2) return;

  const mobileView = window.matchMedia('(max-width: 560px)');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let activeIndex = 0;
  let timer;

  function showSlide(index) {
    activeIndex = (index + slides.length) % slides.length;
    track.style.transform = `translateX(-${slides[activeIndex].offsetLeft}px)`;
  }

  function stopTimer() {
    window.clearInterval(timer);
    timer = undefined;
  }

  function restartTimer() {
    stopTimer();
    if (
      !mobileView.matches
      || reducedMotion.matches
      || document.hidden
    ) {
      return;
    }
    timer = window.setInterval(() => showSlide(activeIndex + 1), 4500);
  }

  document.addEventListener('visibilitychange', restartTimer);
  mobileView.addEventListener('change', () => {
    if (mobileView.matches) showSlide(0);
    else track.style.transform = '';
    restartTimer();
  });
  reducedMotion.addEventListener('change', restartTimer);

  if (mobileView.matches) showSlide(0);
  restartTimer();
})();
