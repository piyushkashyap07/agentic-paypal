import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// jsdom has no scrollIntoView; Chat calls it after every message.
Element.prototype.scrollIntoView = () => {};

afterEach(cleanup);
