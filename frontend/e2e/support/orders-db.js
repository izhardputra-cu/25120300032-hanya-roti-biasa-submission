import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const BACKEND_DIR = fileURLToPath(new URL('../../../backend', import.meta.url))

// Orders keep schedules/products referenced, so local E2E cleanup removes the
// synthetic order rows first through the guarded test-DB script.
export function purgeOrders() {
  execFileSync(
    'uv',
    ['run', '--frozen', '--env-file', '../.env', 'python', 'tests/cleanup_e2e.py'],
    { cwd: BACKEND_DIR, stdio: 'pipe' },
  )
}
