/**
 * Type declarations for react-syntax-highlighter (no official @types package
 * matches v16). Minimal surface for our usage: Prism component + style map.
 */

declare module "react-syntax-highlighter" {
  import { ComponentType } from "react";

  interface HighlighterProps {
    language?: string;
    style?: Record<string, unknown>;
    customStyle?: Record<string, string | number>;
    showLineNumbers?: boolean;
    lineNumberStyle?: Record<string, string | number>;
    children: string;
    [key: string]: unknown;
  }

  export const Prism: ComponentType<HighlighterProps>;
  export const Light: ComponentType<HighlighterProps>;
}

declare module "react-syntax-highlighter/dist/esm/styles/prism" {
  export const oneDark: Record<string, unknown>;
  export const oneLight: Record<string, unknown>;
}
