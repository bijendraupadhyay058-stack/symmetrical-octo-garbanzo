'use client'

import type { ReactNode } from 'react'
import { AppProvider } from './app-provider'
import { FeedbackProvider } from './feedback'
import { ServiceWorkerRegistrar } from './sw-registrar'

export function Providers({ children }: { children: ReactNode }) {
  return (
    <FeedbackProvider>
      <AppProvider>
        <ServiceWorkerRegistrar />
        {children}
      </AppProvider>
    </FeedbackProvider>
  )
}
