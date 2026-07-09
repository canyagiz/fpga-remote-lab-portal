import { useRef } from "react";

// Plays once on mount (page load/refresh). If it has already finished and
// the user hovers over it again, it replays from the start - same pattern
// as the hero mark on bodyformer.app. Framed as a rounded/shadowed "screen"
// rather than blended flush into the page background: the source video has
// its own light-gray gradient background that doesn't match the page's
// near-white background, so a deliberate frame reads better than an
// unintended color seam around the video.
export default function HeroVideo() {
  const videoRef = useRef<HTMLVideoElement>(null);

  function handleMouseEnter() {
    const video = videoRef.current;
    if (video && video.ended) {
      video.currentTime = 0;
      video.play();
    }
  }

  return (
    <video
      ref={videoRef}
      autoPlay
      muted
      playsInline
      onMouseEnter={handleMouseEnter}
      className="mx-auto mb-4 h-64 w-auto max-w-full rounded-2xl shadow-lg sm:h-72"
    >
      <source src="/hero-animation.mp4" type="video/mp4" />
    </video>
  );
}
