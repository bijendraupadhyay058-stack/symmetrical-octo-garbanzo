'use client'

import Link from 'next/link'
import { ChevronRight } from 'lucide-react'
import { menuSections } from '@/components/app-shell'
import { PageHeader } from '@/components/ui'

export default function MorePage() {
  return (
    <div className="space-y-4">
      <PageHeader title="More" />
      {menuSections.map((s) => (
        <section key={s.title}>
          <h2 className="mb-2 text-xs font-bold tracking-wider text-muted uppercase">{s.title}</h2>
          <div className="card divide-y divide-line overflow-hidden">
            {s.items.map((it) => (
              <Link key={it.href + it.label} href={it.href} className="flex items-center gap-3 px-4 py-3.5 hover:bg-elev">
                <it.icon className="size-5 text-balance" /><span className="flex-1 font-medium">{it.label}</span><ChevronRight className="size-4 text-muted" />
              </Link>
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}
