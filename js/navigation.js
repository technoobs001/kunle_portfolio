
document.addEventListener("DOMContentLoaded", () => {
  const header = document.querySelector(".nav");
  const toggle = document.querySelector(".nav__toggle");
  const navigation = document.querySelector(".nav__pill");

  if (!header || !toggle || !navigation) return;

  const closeMenu = () => {
    header.classList.remove("is-open");

    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-label", "Open navigation");
  };

  const openMenu = () => {
    header.classList.add("is-open");

    toggle.setAttribute("aria-expanded", "true");
    toggle.setAttribute("aria-label", "Close navigation");
  };

  toggle.addEventListener("click", () => {
    const isOpen = header.classList.contains("is-open");

    if (isOpen) {
      closeMenu();
    } else {
      openMenu();
    }
  });

  // Close when a navigation link is selected
  navigation.querySelectorAll("a").forEach((link) => {
    link.addEventListener("click", closeMenu);
  });

  // Close with Escape
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeMenu();
    }
  });

  // Close if the screen returns to desktop size
  window.addEventListener("resize", () => {
    if (window.innerWidth > 640) {
      closeMenu();
    }
  });
});
