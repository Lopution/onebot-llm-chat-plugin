import { defineStore } from 'pinia'
import {
  listCorpora,
  listDocuments,
  listChunks,
  ingestKnowledge,
  deleteDocument,
} from '../api/modules/knowledge'

export const useKnowledgeStore = defineStore('knowledge', {
  state: () => ({
    loading: false,
    error: '',
    lastLoadedAt: 0,
    corpora: [] as Array<Record<string, any>>,
    selectedCorpus: 'default',
    documents: [] as Array<Record<string, any>>,
    chunks: [] as Array<Record<string, any>>,
  }),
  actions: {
    async loadCorpora() {
      this.loading = true
      this.error = ''
      try {
        this.corpora = await listCorpora()
        if (!this.corpora.length) {
          this.corpora = [{ corpus_id: 'default', doc_count: 0, chunk_count: 0 }]
        }
        if (!this.selectedCorpus) {
          this.selectedCorpus = this.corpora[0].corpus_id
        }
        this.lastLoadedAt = Date.now()
      } catch (error) {
        this.error = String(error)
      } finally {
        this.loading = false
      }
    },
    async loadDocuments() {
      this.documents = await listDocuments(this.selectedCorpus)
      this.chunks = []
    },
    async loadChunks(docId: string) {
      this.chunks = await listChunks(this.selectedCorpus, docId)
    },
    async removeDocument(docId: string) {
      await deleteDocument(this.selectedCorpus, docId)
      await this.loadCorpora()
      await this.loadDocuments()
    },
    async ingest(title: string, content: string) {
      await ingestKnowledge({
        corpus_id: this.selectedCorpus,
        title,
        content,
      })
      await this.loadCorpora()
      await this.loadDocuments()
    },
    async selectCorpus(corpusId: string) {
      this.selectedCorpus = corpusId
      await this.loadDocuments()
    },
    resetError() {
      this.error = ''
    },
  },
})
