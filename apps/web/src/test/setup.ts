import "@testing-library/jest-dom/vitest";

// jsdom has no scrolling; the router calls window.scrollTo on navigation
window.scrollTo = () => {};
