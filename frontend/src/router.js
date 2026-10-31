import { createRouter, createWebHistory } from 'vue-router'
import { safeRedirect } from './navigation'
import { loadSession, session } from './session'
import AccountView from './views/AccountView.vue'
import CartView from './views/CartView.vue'
import CatalogView from './views/CatalogView.vue'
import JadwalView from './views/JadwalView.vue'
import LoginView from './views/LoginView.vue'
import NotFoundView from './views/NotFoundView.vue'
import OrderDetailView from './views/OrderDetailView.vue'
import OrdersView from './views/OrdersView.vue'
import ProductionRecapView from './views/ProductionRecapView.vue'
import RegisterView from './views/RegisterView.vue'
import SellerOrderDetailView from './views/SellerOrderDetailView.vue'
import SellerOrdersView from './views/SellerOrdersView.vue'
import SellerScheduleView from './views/SellerScheduleView.vue'
import SellerView from './views/SellerView.vue'

const routes = [
  {
    path: '/',
    name: 'catalog',
    component: CatalogView,
    meta: { title: 'Katalog' },
  },
  {
    path: '/jadwal',
    name: 'schedules',
    component: JadwalView,
    meta: { title: 'Jadwal pre-order' },
  },
  {
    path: '/masuk',
    name: 'login',
    component: LoginView,
    meta: { title: 'Masuk', guestOnly: true },
  },
  {
    path: '/daftar',
    name: 'register',
    component: RegisterView,
    meta: { title: 'Daftar pembeli', guestOnly: true },
  },
  {
    path: '/akun',
    name: 'account',
    component: AccountView,
    meta: { title: 'Akun pembeli', requiresAuth: true },
  },
  {
    path: '/keranjang',
    name: 'cart',
    component: CartView,
    meta: { title: 'Tinjauan pesanan', requiresAuth: true },
  },
  {
    path: '/pesanan',
    name: 'orders',
    component: OrdersView,
    meta: { title: 'Pesanan saya', requiresAuth: true },
  },
  {
    path: '/pesanan/:id(\\d+)',
    name: 'order-detail',
    component: OrderDetailView,
    meta: { title: 'Detail pesanan', requiresAuth: true },
  },
  {
    path: '/penjual',
    name: 'seller',
    component: SellerView,
    meta: { title: 'Kelola katalog', requiresAuth: true },
  },
  {
    path: '/penjual/jadwal',
    name: 'seller-schedules',
    component: SellerScheduleView,
    meta: { title: 'Kelola jadwal', requiresAuth: true },
  },
  {
    path: '/penjual/pesanan',
    name: 'seller-orders',
    component: SellerOrdersView,
    meta: { title: 'Pesanan masuk', requiresAuth: true },
  },
  {
    path: '/penjual/pesanan/:id(\\d+)',
    name: 'seller-order-detail',
    component: SellerOrderDetailView,
    meta: { title: 'Tindakan pesanan', requiresAuth: true },
  },
  {
    path: '/penjual/rekap',
    name: 'seller-recap',
    component: ProductionRecapView,
    meta: { title: 'Rekap produksi', requiresAuth: true },
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: NotFoundView,
    meta: { title: 'Halaman tidak ditemukan' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior() {
    return { top: 0 }
  },
})

router.beforeEach(async (to) => {
  try {
    await loadSession()
  } catch {
    return true
  }
  if (to.meta.requiresAuth && !session.user) {
    // Keep the destination so a buyer returns to the review after signing in.
    return { name: 'login', query: { masuk: '1', redirect: to.fullPath } }
  }
  if (to.meta.guestOnly && session.user) {
    return (
      safeRedirect(to.query.redirect) ||
      { name: session.user.role === 'seller' ? 'seller' : 'account' }
    )
  }
  return true
})

router.afterEach((to) => {
  const page = to.meta.title || 'Akun'
  document.title = `${page} | Hanya Roti Biasa`
})

export default router
