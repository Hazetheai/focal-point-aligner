#!/usr/bin/env node
/**
 * Cross-platform launcher for the GUI stack.
 * macOS/Linux → bash scripts/dev.sh
 * Windows → powershell scripts/dev.ps1
 */
import { spawn } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(here, '..')
const isWin = process.platform === 'win32'

const child = isWin
  ? spawn(
      'powershell.exe',
      [
        '-NoProfile',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        path.join(here, 'dev.ps1'),
      ],
      { cwd: root, stdio: 'inherit', windowsHide: true },
    )
  : spawn('bash', [path.join(here, 'dev.sh')], {
      cwd: root,
      stdio: 'inherit',
    })

child.on('exit', (code, signal) => {
  if (signal) process.kill(process.pid, signal)
  process.exit(code ?? 1)
})
