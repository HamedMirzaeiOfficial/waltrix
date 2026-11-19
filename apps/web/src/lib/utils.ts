import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

export function shortId(id: string | null | undefined, size = 8): string {
  return id ? id.slice(0, size) : "-";
}
