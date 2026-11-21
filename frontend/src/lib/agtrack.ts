export const apiBaseUrl = (
  import.meta.env.VITE_API_BASE_URL ??
  import.meta.env.VITE_API_URL ??
  ""
).replace(/\/$/, "")

export function liberianPhone(value: string) {
  return /^\+231\d{7,9}$/.test(value.replace(/[\s()-]/g, ""))
}
