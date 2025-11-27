import './assets/main.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import PrimeVue from 'primevue/config'
import Aura from '@primevue/themes/aura'

import App from './App.vue'
import router from './router'

// PrimeVue components
import Button from 'primevue/button'
import Card from 'primevue/card'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Tag from 'primevue/tag'
import Panel from 'primevue/panel'
import Textarea from 'primevue/textarea'
import Message from 'primevue/message'
import ProgressSpinner from 'primevue/progressspinner'
import Timeline from 'primevue/timeline'
import Divider from 'primevue/divider'
import Chip from 'primevue/chip'
import Badge from 'primevue/badge'
import Dropdown from 'primevue/dropdown'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(PrimeVue, {
  theme: {
    preset: Aura,
    options: {
      darkModeSelector: false, // Light mode only
      cssLayer: false
    }
  }
})

// Register PrimeVue components globally
app.component('Button', Button)
app.component('Card', Card)
app.component('DataTable', DataTable)
app.component('Column', Column)
app.component('Tag', Tag)
app.component('Panel', Panel)
app.component('Textarea', Textarea)
app.component('Message', Message)
app.component('ProgressSpinner', ProgressSpinner)
app.component('Timeline', Timeline)
app.component('Divider', Divider)
app.component('Chip', Chip)
app.component('Badge', Badge)
app.component('Dropdown', Dropdown)

app.mount('#app')
