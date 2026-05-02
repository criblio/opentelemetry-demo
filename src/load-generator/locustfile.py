#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import json
import os
import random
import uuid
import logging

from locust import HttpUser, task, between
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

class WebsiteUser(HttpUser):
    wait_time = between(1, 10)

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

    @task(1)
    def index(self):
        with self.tracer.start_as_current_span("user_index", context=self.session_context):
            logging.info("User accessing index page")
            self.client.get("/")

    @task(10)
    def browse_product(self):
        product = self._pick_product()
        with self.tracer.start_as_current_span("user_browse_product", context=self.session_context, attributes={"product.id": product}):
            logging.info(f"User browsing product: {product}")
            self.client.get("/api/products/" + product, params=self._params())

    @task(3)
    def get_recommendations(self):
        product = self._pick_product()
        with self.tracer.start_as_current_span("user_get_recommendations", context=self.session_context, attributes={"product.id": product}):
            logging.info(f"User getting recommendations for product: {product}")
            self.client.get("/api/recommendations", params=self._params(productIds=[product]))

    @task(3)
    def get_ads(self):
        category = random.choice(categories)
        with self.tracer.start_as_current_span("user_get_ads", context=self.session_context, attributes={"category": str(category)}):
            logging.info(f"User getting ads for category: {category}")
            self.client.get("/api/data/", params=self._params(contextKeys=[category]))

    @task(3)
    def view_cart(self):
        with self.tracer.start_as_current_span("user_view_cart", context=self.session_context):
            logging.info("User viewing cart")
            self.client.get("/api/cart", params=self._params())

    @task(2)
    def add_to_cart(self, user=""):
        if user == "":
            user = str(uuid.uuid1())
        product = self._pick_product()
        quantity = random.choice([1, 2, 3, 4, 5, 10])
        with self.tracer.start_as_current_span("user_add_to_cart", context=self.session_context, attributes={"user.id": user, "product.id": product, "quantity": quantity}):
            logging.info(f"User {user} adding {quantity} of product {product} to cart")
            self.client.get("/api/products/" + product, params=self._params())
            cart_item = {
                "item": {
                    "productId": product,
                    "quantity": quantity,
                },
                "userId": user,
            }
            self.client.post("/api/cart", json=cart_item, params=self._params())

    @task(1)
    def checkout(self):
        user = str(uuid.uuid1())
        with self.tracer.start_as_current_span("user_checkout_single", context=self.session_context, attributes={"user.id": user}):
            self.add_to_cart(user=user)
            checkout_person = random.choice(people)
            checkout_person["userId"] = user
            self.client.post("/api/checkout", json=checkout_person, params=self._params())
            logging.info(f"Checkout completed for user {user}")

    @task(1)
    def checkout_multi(self):
        user = str(uuid.uuid1())
        item_count = random.choice([2, 3, 4])
        with self.tracer.start_as_current_span("user_checkout_multi", context=self.session_context,
                                            attributes={"user.id": user, "item.count": item_count}):
            for i in range(item_count):
                self.add_to_cart(user=user)
            checkout_person = random.choice(people)
            checkout_person["userId"] = user
            self.client.post("/api/checkout", json=checkout_person, params=self._params())
            logging.info(f"Multi-item checkout completed for user {user}")

    @task(5)
    def flood_home(self):
        flood_count = get_flagd_value("loadGeneratorFloodHomepage")
        if flood_count > 0:
            with self.tracer.start_as_current_span("user_flood_home",  context=self.session_context, attributes={"flood.count": flood_count}):
                logging.info(f"User flooding homepage {flood_count} times")
                for _ in range(0, flood_count):
                    self.client.get("/")

    @task(2)
    def bad_request(self):
        # Steady trickle of 4xx-producing requests modeling bots, scrapers,
        # broken bookmarks, and typo'd URLs. NOT tagged as synthetic — the
        # APM app must surface/group/silence these on its own merits. The
        # 4xx will count toward Locust's failure stats, which is realistic
        # for an operator's view of the world. name= groups the per-id
        # requests under one stats row so the locust UI stays readable.
        bad = random.choice(invalid_product_ids)
        with self.tracer.start_as_current_span("user_bad_request", context=self.session_context, attributes={"product.id": bad}):
            self.client.get(f"/api/products/{bad}", params=self._params(),
                            name="/api/products/[invalid]")

    def on_start(self):
        session_id = str(uuid.uuid4())
        logging.info(f"Starting user session: {session_id}")
        # Per-user persona: language/UA + currency. Locust's HttpUser session
        # holds these as defaults, applied to every request.
        accept_lang, user_agent = random.choice(user_profiles)
        self.client.headers.update({
            "Accept-Language": accept_lang,
            "User-Agent": user_agent,
        })
        self.currency = random.choices(currencies, weights=currency_weights, k=1)[0]
        logging.info(f"Session profile: lang={accept_lang!r} currency={self.currency} ua={user_agent[:40]!r}")
        ctx = baggage.set_baggage("session.id", session_id)
        ctx = baggage.set_baggage("synthetic_request", "true", context=ctx)
        # Stash for use as parent context in every task — keeps each task as
        # its own trace root (no parent span) while letting baggage flow.
        self.session_context = ctx
        context.attach(ctx)
        with self.tracer.start_as_current_span("user_session_start", context=self.session_context):
            self.index()


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
