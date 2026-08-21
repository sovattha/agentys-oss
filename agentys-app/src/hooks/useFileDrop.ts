import { useCallback, useRef, useState } from 'react'

export interface UseFileDropOptions {
  onDrop: (files: File[]) => void
  enabled?: boolean
}

export interface UseFileDropResult {
  isDragging: boolean
  dropZoneProps: {
    onDragEnter: (e: React.DragEvent) => void
    onDragLeave: (e: React.DragEvent) => void
    onDragOver: (e: React.DragEvent) => void
    onDrop: (e: React.DragEvent) => void
  }
}

function readEntryAsFiles(entry: FileSystemEntry): Promise<File[]> {
  return new Promise((resolve) => {
    if (entry.isFile) {
      ;(entry as FileSystemFileEntry).file(
        (file) => resolve([file]),
        () => resolve([]),
      )
    } else if (entry.isDirectory) {
      const reader = (entry as FileSystemDirectoryEntry).createReader()
      const collected: FileSystemEntry[] = []
      const readBatch = () => {
        reader.readEntries(
          (entries) => {
            if (entries.length === 0) {
              Promise.all(collected.map(readEntryAsFiles)).then((nested) =>
                resolve(nested.flat()),
              )
            } else {
              collected.push(...entries)
              readBatch()
            }
          },
          () => resolve([]),
        )
      }
      readBatch()
    } else {
      resolve([])
    }
  })
}

async function extractFilesFromDataTransfer(dt: DataTransfer): Promise<File[]> {
  if (dt.items && dt.items.length > 0) {
    const fallbackFiles: File[] = []
    const entries: FileSystemEntry[] = []
    for (let i = 0; i < dt.items.length; i++) {
      const item = dt.items[i]
      if (item.kind !== 'file') continue
      const entry = (item as DataTransferItem & {
        webkitGetAsEntry?: () => FileSystemEntry | null
      }).webkitGetAsEntry?.()
      if (entry) {
        entries.push(entry)
      } else {
        const f = item.getAsFile()
        if (f) fallbackFiles.push(f)
      }
    }
    if (entries.length > 0) {
      const nested = await Promise.all(entries.map(readEntryAsFiles))
      return [...fallbackFiles, ...nested.flat()]
    }
    return fallbackFiles
  }
  return Array.from(dt.files || [])
}

export function useFileDrop({
  onDrop,
  enabled = true,
}: UseFileDropOptions): UseFileDropResult {
  const [isDragging, setIsDragging] = useState(false)
  const counterRef = useRef(0)
  const onDropRef = useRef(onDrop)
  onDropRef.current = onDrop

  const containsFiles = (e: React.DragEvent) =>
    !!e.dataTransfer && Array.from(e.dataTransfer.types).includes('Files')

  const handleDragEnter = useCallback(
    (e: React.DragEvent) => {
      if (!enabled || !containsFiles(e)) return
      e.preventDefault()
      counterRef.current += 1
      setIsDragging(true)
    },
    [enabled],
  )

  const handleDragLeave = useCallback(
    (e: React.DragEvent) => {
      if (!enabled || !containsFiles(e)) return
      e.preventDefault()
      counterRef.current = Math.max(0, counterRef.current - 1)
      if (counterRef.current === 0) setIsDragging(false)
    },
    [enabled],
  )

  const handleDragOver = useCallback(
    (e: React.DragEvent) => {
      if (!enabled || !containsFiles(e)) return
      e.preventDefault()
      e.dataTransfer.dropEffect = 'copy'
    },
    [enabled],
  )

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      if (!enabled || !containsFiles(e)) return
      e.preventDefault()
      counterRef.current = 0
      setIsDragging(false)
      const dt = e.dataTransfer
      void extractFilesFromDataTransfer(dt).then((files) => {
        if (files.length > 0) onDropRef.current(files)
      })
    },
    [enabled],
  )

  return {
    isDragging,
    dropZoneProps: {
      onDragEnter: handleDragEnter,
      onDragLeave: handleDragLeave,
      onDragOver: handleDragOver,
      onDrop: handleDrop,
    },
  }
}
