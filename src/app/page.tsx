'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useApp } from '@/components/app-provider'
import { Splash } from '@/components/splash'

export default function Index() {
  const { phase } = useApp()
  const router = useRouter()
  useEffect(() => {
    if (phase === 'ready') router.replace('/dashboard')
    else if (phase === 'signed-out') router.replace('/login')
  }, [phase, router])
  return <Splash />
}
