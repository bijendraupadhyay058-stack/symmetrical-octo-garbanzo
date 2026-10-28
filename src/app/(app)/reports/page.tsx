'use client'

import Link from 'next/link'
import { ChevronRight } from 'lucide-react'
import { PageHeader } from '@/components/ui'
import { REPORTS } from '@/lib/reports/reports'

export default function ReportsPage() {
  const groups = [...new Set(REPORTS.map((r) => r.group))]
  return (
    <div>
      <PageHeader title="Reports" subtitle="Every report can be filtered, printed and downloaded as PDF or Excel" />
      <div className="space-y-5">
        {groups.map((g) => (
          <section key={g}>
            <h2 className="mb-2 text-xs font-bold tracking-wider text-muted uppercase">{g}</h2>
            <div className="card divide-y divide-line overflow-hidden">
              {REPORTS.filter((r) => r.group === g).map((r) => (
                <Link key={r.id} href={`/reports/view?r=${r.id}`} className="flex items-center gap-3 px-4 py-3.5 hover:bg-elev">
                  <div className="min-w-0 flex-1">
                    <div className="font-semibold">{r.title}</div>
                    <div className="text-xs text-muted">{r.description}</div>
                  </div>
                  <ChevronRight className="size-4 text-muted" />
                </Link>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}
