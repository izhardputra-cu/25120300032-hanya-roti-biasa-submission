// Only internal paths are accepted as a post-login destination; an absolute URL
// (or protocol-relative path) would turn the return-to-cart flow into an open
// redirect.
export function safeRedirect(value) {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//')) {
    return null
  }
  if (value.includes('\\')) {
    return null
  }
  return value
}
