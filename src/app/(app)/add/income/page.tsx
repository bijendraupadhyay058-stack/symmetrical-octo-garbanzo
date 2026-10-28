'use client'

import { Suspense } from 'react'
import { useSearchParams } from 'next/navigation'
import { TransactionForm } from '@/components/transaction-form'

function Inner() {
  const p = useSearchParams()
  const id = p.get('id')
  return <TransactionForm key={id ?? 'new'} type="income" editId={id} templateId={p.get('template')} clientId={p.get('client')} />
}

export default function Page() {
  return (
    <Suspense>
      <Inner />
    </Suspense>
  )
}
