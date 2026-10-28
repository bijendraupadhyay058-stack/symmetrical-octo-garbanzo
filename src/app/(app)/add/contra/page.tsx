'use client'

import { Suspense } from 'react'
import { useSearchParams } from 'next/navigation'
import { TransactionForm } from '@/components/transaction-form'

function Inner() {
  const p = useSearchParams()
  const id = p.get('id')
  return <TransactionForm key={id ?? 'new'} type="contra" editId={id} templateId={p.get('template')} />
}

export default function Page() {
  return (
    <Suspense>
      <Inner />
    </Suspense>
  )
}
