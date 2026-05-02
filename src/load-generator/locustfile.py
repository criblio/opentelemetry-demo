#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import json
import os
import random
import uuid
import logging

from locust import HttpUser, LoadTestShape, task, between
from locust_plugins.users.playwright import PlaywrightUser, pw, PageWithRetry, event

from opentelemetry import context, baggage, trace
from opentelemetry.context import Context
from opentelemetry.metrics import set_meter_provider
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.jinja2 import Jinja2Instrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.system_metrics import SystemMetricsInstrumentor
from opentelemetry.instrumentation.urllib3 import URLLib3Instrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.processor.baggage import BaggageSpanProcessor

from openfeature import api
from openfeature.contrib.provider.ofrep import OFREPProvider
from openfeature.contrib.hook.opentelemetry import TracingHook

from playwright.async_api import Route, Request

# Configure tracer provider first (needed for trace context in logs)
tracer_provider = TracerProvider()
trace.set_tracer_provider(tracer_provider)
tracer_provider.add_span_processor(BaggageSpanProcessor(lambda key: key == "session.id"))
tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(insecure=True)))

# Configure logger provider with the same resource
logger_provider = LoggerProvider()
set_logger_provider(logger_provider)

# Set up log exporter and processor
log_exporter = OTLPLogExporter(insecure=True)
logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))

# Create logging handler that will include trace context
handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)

# Configure root logger
root_logger = logging.getLogger()
root_logger.addHandler(handler)
root_logger.setLevel(logging.INFO)

# Configure metrics
metric_exporter = OTLPMetricExporter(insecure=True)
set_meter_provider(MeterProvider([PeriodicExportingMetricReader(metric_exporter)]))

# Instrument logging to automatically inject trace context
LoggingInstrumentor().instrument(set_logging_format=True)

# Instrumenting manually to avoid error with locust gevent monkey
Jinja2Instrumentor().instrument()
RequestsInstrumentor().instrument()
SystemMetricsInstrumentor().instrument()
URLLib3Instrumentor().instrument()

logging.info("Instrumentation complete - logs will now include trace context")

# Initialize Flagd provider
base_url = f"http://{os.environ.get('FLAGD_HOST', 'localhost')}:{os.environ.get('FLAGD_OFREP_PORT', 8016)}"
api.set_provider(OFREPProvider(base_url=base_url))
api.add_hooks([TracingHook()])

def get_flagd_value(FlagName):
    # Initialize OpenFeature
    client = api.get_client()
    return client.get_integer_value(FlagName, 0)

categories = [
    "binoculars",
    "telescopes",
    "accessories",
    "assembly",
    "travel",
    "books",
    None,
]

# Real product IDs from src/product-catalog/products/products.json. Weighted
# so a few SKUs dominate (head) and the rest see long-tail traffic — the
# Pareto-style shape real e-commerce sites see.
products = [
    "OLJCESPC7Z",  # head
    "66VCHSJNUP",
    "0PUK6V6EV0",
    "1YMWWN1N4O",
    "L9ECAV7KIM",
    "2ZYFJ3GM2N",
    "6E92ZMYYFZ",
    "9SIQT8TOJO",
    "LS4PSXUNUM",
    "HQTGWGPNH4",  # tail
]
product_weights = [10, 7, 5, 4, 3, 2, 2, 1, 1, 1]

# Drives intentional 4xx traffic. Real production traffic gets bots/scrapers
# /broken bookmarks/typo'd URLs hitting paths like these; the APM app must
# cope without help. Per docs/load-generator-traffic-plan.md: do NOT tag
# these so the APM can filter them out — that defeats the test.
invalid_product_ids = [
    "DEADBEEF99",   # well-formed but unknown
    "NOTAPRODUCT",
    "12345",
    "../../etc/passwd",  # path-traversal-ish; should bounce
    "%00",           # null byte
]

# (Accept-Language, User-Agent) tuples picked at on_start. Mix of desktop,
# mobile, and a small fraction of bot-ish UAs so the APM can demonstrate
# UA/locale facets and bot filtering.
user_profiles = [
    ("en-US,en;q=0.9", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"),
    ("en-GB,en;q=0.9", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2.1 Safari/605.1.15"),
    ("de-DE,de;q=0.9,en;q=0.8", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"),
    ("ja-JP,ja;q=0.9,en;q=0.8", "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1"),
    ("fr-FR,fr;q=0.9,en;q=0.8", "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36"),
    ("es-ES,es;q=0.9,en;q=0.8", "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0"),
    ("zh-CN,zh;q=0.9", "Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"),
    # Bot-ish UAs — small slice of real traffic; APM should be able to
    # surface or filter these without our help.
    ("en-US,en;q=0.5", "curl/8.4.0"),
    ("en-US,en;q=0.5", "python-requests/2.31.0"),
]

# Currency codes the demo's currency service supports, weighted toward
# USD so most traffic is the home currency.
currencies = ["USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "INR"]
currency_weights = [40, 15, 10, 8, 6, 6, 5, 10]

people_file = open('people.json')
people = json.load(people_file)

# Subset of user_profiles whose UA looks mobile — used by the Mobile persona
# so its sessions consistently look like phone traffic.
mobile_user_profiles = [p for p in user_profiles if 'iPhone' in p[1] or 'Android' in p[1]]


# === Module-level task functions ============================================
# Each takes a User instance (locust passes `self` as the first arg when a
# bare callable is in the User's tasks list). Defining them at module level
# (rather than as @task methods on a class) lets multiple persona classes
# compose their own task mixes without inheritance gymnastics.

def t_index(user):
    with user.tracer.start_as_current_span("user_index", context=user.session_context):
        user.client.get("/")

def t_browse_product(user):
    product = user._pick_product()
    with user.tracer.start_as_current_span("user_browse_product", context=user.session_context, attributes={"product.id": product}):
        user.client.get("/api/products/" + product, params=user._params())

def t_get_recommendations(user):
    product = user._pick_product()
    with user.tracer.start_as_current_span("user_get_recommendations", context=user.session_context, attributes={"product.id": product}):
        user.client.get("/api/recommendations", params=user._params(productIds=[product]))

def t_get_ads(user):
    category = random.choice(categories)
    with user.tracer.start_as_current_span("user_get_ads", context=user.session_context, attributes={"category": str(category)}):
        user.client.get("/api/data/", params=user._params(contextKeys=[category]))

def t_view_cart(user):
    with user.tracer.start_as_current_span("user_view_cart", context=user.session_context):
        user.client.get("/api/cart", params=user._params())

def _add_to_cart(user, user_id):
    """Underlying add-to-cart helper; called as a task and from checkout flows."""
    product = user._pick_product()
    quantity = random.choice([1, 2, 3, 4, 5, 10])
    with user.tracer.start_as_current_span("user_add_to_cart", context=user.session_context, attributes={"user.id": user_id, "product.id": product, "quantity": quantity}):
        user.client.get("/api/products/" + product, params=user._params())
        cart_item = {"item": {"productId": product, "quantity": quantity}, "userId": user_id}
        user.client.post("/api/cart", json=cart_item, params=user._params())

def t_add_to_cart(user):
    _add_to_cart(user, str(uuid.uuid1()))

def t_checkout(user):
    user_id = str(uuid.uuid1())
    with user.tracer.start_as_current_span("user_checkout_single", context=user.session_context, attributes={"user.id": user_id}):
        _add_to_cart(user, user_id)
        person = random.choice(people)
        person["userId"] = user_id
        user.client.post("/api/checkout", json=person, params=user._params())

def t_checkout_multi(user):
    user_id = str(uuid.uuid1())
    item_count = random.choice([2, 3, 4])
    with user.tracer.start_as_current_span("user_checkout_multi", context=user.session_context, attributes={"user.id": user_id, "item.count": item_count}):
        for _ in range(item_count):
            _add_to_cart(user, user_id)
        person = random.choice(people)
        person["userId"] = user_id
        user.client.post("/api/checkout", json=person, params=user._params())

def t_flood_home(user):
    flood_count = get_flagd_value("loadGeneratorFloodHomepage")
    if flood_count > 0:
        with user.tracer.start_as_current_span("user_flood_home", context=user.session_context, attributes={"flood.count": flood_count}):
            for _ in range(flood_count):
                user.client.get("/")

def t_bad_request(user):
    # Steady trickle of 4xx-producing requests modeling bots, scrapers,
    # broken bookmarks, and typo'd URLs. NOT tagged as synthetic — the
    # APM app must surface/group/silence these on its own merits. The
    # 4xx counts toward Locust's failure stats, which is what an operator
    # would see. name= groups the per-id requests under one stats row.
    bad = random.choice(invalid_product_ids)
    with user.tracer.start_as_current_span("user_bad_request", context=user.session_context, attributes={"product.id": bad}):
        user.client.get(f"/api/products/{bad}", params=user._params(), name="/api/products/[invalid]")


# === Persona classes ========================================================
# Each persona is a separate HttpUser class with its own task mix and
# wait_time. `weight` controls the spawn ratio across personas.

class _BaseUser(HttpUser):
    abstract = True  # locust won't spawn instances of the base class
    profile_pool = user_profiles  # subclasses can narrow (Mobile does)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tracer = trace.get_tracer(__name__)
        # Default until on_start() runs; ensures tasks always have a valid
        # parent context even if Locust schedules one before on_start finishes.
        self.session_context = Context()
        self.currency = "USD"

    def _pick_product(self):
        return random.choices(products, weights=product_weights, k=1)[0]

    def _params(self, **extra):
        # currencyCode goes on every API call so the BFF threads it through
        # to currency / product-catalog / shipping. extra lets callers add
        # task-specific params (productIds, contextKeys, …).
        p = {"currencyCode": self.currency}
        p.update(extra)
        return p

    def on_start(self):
        session_id = str(uuid.uuid4())
        accept_lang, user_agent = random.choice(self.profile_pool)
        self.client.headers.update({
            "Accept-Language": accept_lang,
            "User-Agent": user_agent,
        })
        self.currency = random.choices(currencies, weights=currency_weights, k=1)[0]
        logging.info(f"[{type(self).__name__}] session={session_id[:8]} lang={accept_lang!r} currency={self.currency} ua={user_agent[:40]!r}")
        ctx = baggage.set_baggage("session.id", session_id)
        ctx = baggage.set_baggage("synthetic_request", "true", context=ctx)
        # Stash for use as parent context in every task — keeps each task as
        # its own trace root (no parent span) while letting baggage flow.
        self.session_context = ctx
        context.attach(ctx)
        # Every persona starts with a homepage hit, simulating an arrival.
        with self.tracer.start_as_current_span("user_session_start", context=self.session_context):
            t_index(self)


class Browser(_BaseUser):
    """Window shopper. Heavy browse + recommendations, low cart conversion,
    never checks out. Owns the bad_request slice (most realistic for a
    casual browser to fat-finger URLs or hit stale links)."""
    weight = 6
    wait_time = between(2, 8)
    tasks = {
        t_browse_product: 10,
        t_get_recommendations: 3,
        t_get_ads: 3,
        t_view_cart: 2,
        t_add_to_cart: 1,
        t_index: 1,
        t_flood_home: 2,
        t_bad_request: 2,
    }


class Buyer(_BaseUser):
    """Decisive shopper. Short browse, then checkout. Few task types, high
    conversion."""
    weight = 2
    wait_time = between(1, 3)
    tasks = {
        t_browse_product: 2,
        t_view_cart: 1,
        t_add_to_cart: 3,
        t_checkout: 4,
        t_checkout_multi: 2,
    }


class Abandoner(_BaseUser):
    """Adds items to cart, never checks out. Real e-commerce pain pattern."""
    weight = 2
    wait_time = between(2, 6)
    tasks = {
        t_browse_product: 3,
        t_view_cart: 2,
        t_add_to_cart: 4,
        t_get_recommendations: 2,
        # Intentionally no checkout / checkout_multi.
    }


class Mobile(_BaseUser):
    """Phone user: shorter wait_time, restricted to mobile UAs. Smaller
    catalog interactions, occasional checkout."""
    weight = 3
    wait_time = between(1, 4)
    profile_pool = mobile_user_profiles
    tasks = {
        t_browse_product: 5,
        t_view_cart: 1,
        t_add_to_cart: 2,
        t_checkout: 1,
    }


# === Load shape =============================================================

class StagedSpike(LoadTestShape):
    """
    Deterministic 10-min cycle: warm → ramp → peak (flash sale) → cool → idle.
    Picked deterministic per docs/load-generator-traffic-plan.md so APM
    features can be validated against a known curve. Cycle repeats so the
    pattern is observable indefinitely without re-running locust.
    """
    # (cumulative_seconds_within_cycle, target_users, spawn_rate)
    stages = [
        (60,   5,  1),   # 0-1m: warm-up
        (180, 15,  2),   # 1-3m: morning ramp
        (300, 25,  3),   # 3-5m: peak / flash sale
        (420, 10,  2),   # 5-7m: cool-down
        (600,  5,  1),   # 7-10m: idle
    ]
    cycle_seconds = 600

    def tick(self):
        run_time = self.get_run_time() % self.cycle_seconds
        for stage_time, users, spawn in self.stages:
            if run_time < stage_time:
                return (users, spawn)
        return None  # should be unreachable


browser_traffic_enabled = os.environ.get("LOCUST_BROWSER_TRAFFIC_ENABLED", "").lower() in ("true", "yes", "on")

if browser_traffic_enabled:
    class WebsiteBrowserUser(PlaywrightUser):
        headless = True  # to use a headless browser, without a GUI

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.tracer = trace.get_tracer(__name__)
            self.session_context = Context()

        def on_start(self):
            session_id = str(uuid.uuid4())
            logging.info(f"Starting browser user session: {session_id}")
            ctx = baggage.set_baggage("session.id", session_id)
            ctx = baggage.set_baggage("synthetic_request", "true", context=ctx)
            self.session_context = ctx
            context.attach(ctx)

        @task
        @pw
        async def open_cart_page_and_change_currency(self, page: PageWithRetry):
            with self.tracer.start_as_current_span("browser_change_currency", context=self.session_context):
                try:
                    page.on("console", lambda msg: print(msg.text))
                    await page.route('**/*', add_baggage_header)
                    await page.goto("/cart", wait_until="domcontentloaded")
                    await page.select_option('[name="currency_code"]', 'CHF')
                    await page.wait_for_timeout(2000)  # giving the browser time to export the traces
                    logging.info("Currency changed to CHF")
                except Exception as e:
                    logging.error(f"Error in change currency task: {str(e)}")

        @task
        @pw
        async def add_product_to_cart(self, page: PageWithRetry):
            with self.tracer.start_as_current_span("browser_add_to_cart", context=self.session_context):
                try:
                    page.on("console", lambda msg: print(msg.text))
                    await page.route('**/*', add_baggage_header)
                    await page.goto("/", wait_until="domcontentloaded")
                    await page.click('p:has-text("Roof Binoculars")')
                    await page.wait_for_load_state("domcontentloaded")
                    await page.click('button:has-text("Add To Cart")')
                    await page.wait_for_load_state("domcontentloaded")
                    await page.wait_for_timeout(2000)  # giving the browser time to export the traces
                    logging.info("Product added to cart successfully")
                except Exception as e:
                    logging.error(f"Error in add to cart task: {str(e)}")

async def add_baggage_header(route: Route, request: Request):
    existing_baggage = request.headers.get('baggage', '')
    headers = {
        **request.headers,
        'baggage': ', '.join(filter(None, (existing_baggage, 'synthetic_request=true')))
    }
    await route.continue_(headers=headers)
