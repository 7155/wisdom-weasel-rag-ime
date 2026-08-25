import { useLayoutEffect, type RefObject } from "react";

export function useAutoGrowTextarea(ref: RefObject<HTMLTextAreaElement | null>, value: string, maxHeight = 220) {
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    element.style.height = "0px";
    element.style.height = `${Math.min(element.scrollHeight, maxHeight)}px`;
    element.style.overflowY = element.scrollHeight > maxHeight ? "auto" : "hidden";
  }, [maxHeight, ref, value]);
}
