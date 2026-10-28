// Generates PWA icons from an inline SVG. Run: npm run icons
import sharp from 'sharp'
import { mkdirSync } from 'node:fs'

const mark = (pad) => `
<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
  <rect width="512" height="512" ${pad ? '' : 'rx="112"'} fill="#0b2545"/>
  <g transform="translate(${pad ? 96 : 56} ${pad ? 96 : 56}) scale(${pad ? 5 : 6.25})">
    <path d="M17 44V20h18" stroke="#fff" stroke-width="5" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
    <path d="M17 32h13" stroke="#fff" stroke-width="5" stroke-linecap="round" fill="none"/>
    <path d="M38 44l5-10 5 5 6-13" stroke="#4ade80" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
    <circle cx="47" cy="20" r="3" fill="#8ecae6"/>
  </g>
</svg>`

mkdirSync('public/icons', { recursive: true })
const any = Buffer.from(mark(false))
const maskable = Buffer.from(mark(true))
await sharp(any).resize(192, 192).png().toFile('public/icons/icon-192.png')
await sharp(any).resize(512, 512).png().toFile('public/icons/icon-512.png')
await sharp(maskable).resize(512, 512).png().toFile('public/icons/maskable-512.png')
await sharp(maskable).resize(180, 180).png().toFile('public/icons/apple-touch-icon.png')
await sharp(any).resize(48, 48).png().toFile('public/favicon.png')
console.log('Icons written to public/icons')
