/** @odoo-module **/
/**
 * Stripe Issuing – Card Reveal & Wallet Provisioning
 *
 * Registers two Odoo client actions:
 *   1. dojo_stripe_issuing_reveal – shows full PAN, CVC, expiry via Stripe Issuing Elements
 *   2. dojo_stripe_issuing_wallet – push-provisions the card to Apple Pay / Google Pay
 */
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, xml, onMounted, onWillUnmount } from "@odoo/owl";

// ═══════════════════════════════════════════════════════════════════════════════
// Reveal Card Action
// ═══════════════════════════════════════════════════════════════════════════════

class IssuingRevealAction extends Component {
    static template = xml`
        <div class="o_action d-flex align-items-center justify-content-center" style="min-height:80vh;">
            <div class="card shadow" style="min-width:400px;max-width:500px;">
                <div class="card-header d-flex justify-content-between align-items-center">
                    <h5 class="mb-0"><i class="fa fa-credit-card me-2"/>Card Details</h5>
                    <button class="btn btn-sm btn-outline-secondary" t-on-click="goBack">
                        <i class="fa fa-times"/> Close
                    </button>
                </div>
                <div class="card-body">
                    <div style="background:linear-gradient(135deg,#1a1a2e,#16213e);border-radius:10px;padding:24px;color:#fff;">
                        <div class="mb-3">
                            <div style="font-size:11px;text-transform:uppercase;opacity:0.7;">Card Number</div>
                            <div id="stripe-card-number-display" style="min-height:28px;font-size:20px;letter-spacing:2px;"/>
                        </div>
                        <div class="d-flex gap-4">
                            <div>
                                <div style="font-size:11px;text-transform:uppercase;opacity:0.7;">Expiry</div>
                                <div id="stripe-card-expiry-display" style="min-height:24px;font-size:16px;"/>
                            </div>
                            <div>
                                <div style="font-size:11px;text-transform:uppercase;opacity:0.7;">CVC</div>
                                <div id="stripe-card-cvc-display" style="min-height:24px;font-size:16px;"/>
                            </div>
                        </div>
                    </div>
                    <div class="mt-3 d-flex gap-2 align-items-center">
                        <span class="badge bg-dark" t-esc="props.action.params.card_brand"/>
                        <span class="text-muted">•••• <t t-esc="props.action.params.card_last4"/></span>
                        <span class="text-muted ms-auto" t-esc="props.action.params.card_expiry"/>
                    </div>
                    <p class="text-muted text-center mt-3 mb-0" style="font-size:12px;">
                        <i class="fa fa-lock me-1"/>Card details rendered securely by Stripe — they never touch our servers.
                    </p>
                </div>
            </div>
        </div>`;

    static props = ["*"];

    setup() {
        this.actionService = useService("action");
        this.notification = useService("notification");
        this._mounted = false;

        onMounted(async () => {
            this._mounted = true;
            try {
                await this.mountStripeElements();
            } catch (err) {
                console.error("Stripe Issuing reveal error:", err);
                this.notification.add(
                    err.message || "Failed to reveal card details.",
                    { type: "danger" }
                );
            }
        });

        onWillUnmount(() => {
            this._mounted = false;
        });
    }

    async mountStripeElements() {
        const params = this.props.action.params;
        await ensureStripeScript();
        const stripe = Stripe(params.publishable_key);  // eslint-disable-line no-undef
        const elements = stripe.elements();
        const style = {
            base: { color: "#ffffff", fontSize: "16px", lineHeight: "24px" },
        };

        // Create and mount Issuing display elements.
        // Stripe.js will internally create a nonce, call our /reveal endpoint
        // if configured, or use the ephemeral key from issuingCardEphemeralKeyProvider.
        const cardId = params.stripe_card_id;
        const employeeId = params.employee_id;

        const numberEl = elements.create("issuingCardNumberDisplay", {
            issuingCard: cardId,
            nonce: await this.fetchNonce(stripe, cardId, employeeId),
            ephemeralKeySecret: this._ephemeralKeySecret,
            style,
        });
        const expiryEl = elements.create("issuingCardExpiryDisplay", {
            issuingCard: cardId,
            nonce: this._nonce,
            ephemeralKeySecret: this._ephemeralKeySecret,
            style,
        });
        const cvcEl = elements.create("issuingCardCvcDisplay", {
            issuingCard: cardId,
            nonce: this._nonce,
            ephemeralKeySecret: this._ephemeralKeySecret,
            style,
        });

        if (!this._mounted) return;

        numberEl.mount("#stripe-card-number-display");
        expiryEl.mount("#stripe-card-expiry-display");
        cvcEl.mount("#stripe-card-cvc-display");
    }

    async fetchNonce(stripe, cardId, employeeId) {
        // Stripe.js creates a nonce when we create an issuingCardNumberDisplay
        // element. We need to use the stripe.createEphemeralKeyNonce method.
        const nonceResult = await stripe.createEphemeralKeyNonce({
            issuingCard: cardId,
        });
        if (nonceResult.error) {
            throw new Error(nonceResult.error.message);
        }
        this._nonce = nonceResult.nonce;

        // Now fetch the ephemeral key from our backend using this nonce
        const response = await fetch("/dojo/stripe/issuing/reveal", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Stripe-Issuing-Nonce": nonceResult.nonce,
            },
            body: JSON.stringify({
                jsonrpc: "2.0",
                method: "call",
                params: { employee_id: employeeId },
            }),
        });
        const data = await response.json();
        if (data.error) {
            throw new Error(data.error.data?.message || "Failed to get ephemeral key");
        }
        if (data.result?.error) {
            throw new Error(data.result.error);
        }
        this._ephemeralKeySecret = data.result.ephemeral_key_secret;
        return nonceResult.nonce;
    }

    goBack() {
        this.actionService.doAction({ type: "ir.actions.act_window_close" });
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// Wallet Provisioning Action
// ═══════════════════════════════════════════════════════════════════════════════

class IssuingWalletAction extends Component {
    static template = xml`
        <div class="o_action d-flex align-items-center justify-content-center" style="min-height:80vh;">
            <div class="card shadow" style="min-width:400px;max-width:500px;">
                <div class="card-header d-flex justify-content-between align-items-center">
                    <h5 class="mb-0"><i class="fa fa-mobile me-2"/>Add to Digital Wallet</h5>
                    <button class="btn btn-sm btn-outline-secondary" t-on-click="goBack">
                        <i class="fa fa-times"/> Close
                    </button>
                </div>
                <div class="card-body text-center">
                    <div t-if="state.status === 'loading'" class="py-5">
                        <i class="fa fa-spinner fa-spin fa-3x text-primary"/>
                        <p class="mt-3 text-muted">Starting wallet provisioning…</p>
                    </div>
                    <div t-if="state.status === 'success'" class="py-5">
                        <i class="fa fa-check-circle fa-3x text-success"/>
                        <p class="mt-3">Card has been added to your digital wallet!</p>
                        <button class="btn btn-primary" t-on-click="goBack">Done</button>
                    </div>
                    <div t-if="state.status === 'error'" class="py-5">
                        <i class="fa fa-exclamation-triangle fa-3x text-danger"/>
                        <p class="mt-3 text-danger" t-esc="state.errorMessage"/>
                        <button class="btn btn-outline-secondary" t-on-click="goBack">Close</button>
                    </div>
                    <div t-if="state.status === 'unsupported'" class="py-5">
                        <i class="fa fa-info-circle fa-3x text-warning"/>
                        <p class="mt-3">
                            Digital wallet provisioning is not supported in this browser.
                            Please use a mobile device with Apple Pay or Google Pay.
                        </p>
                        <button class="btn btn-outline-secondary" t-on-click="goBack">Close</button>
                    </div>
                </div>
            </div>
        </div>`;

    static props = ["*"];

    setup() {
        this.actionService = useService("action");
        this.state = owl.reactive({ status: "loading", errorMessage: "" });

        onMounted(async () => {
            await this.startProvisioning();
        });
    }

    async startProvisioning() {
        const params = this.props.action.params;
        try {
            await ensureStripeScript();
            const stripe = Stripe(params.publishable_key);  // eslint-disable-line no-undef

            const result = await stripe.createIssuingCardPushProvisioning({
                ephemeralKeySecret: params.ephemeral_key_secret,
                issuingCard: params.stripe_card_id,
            });

            if (result.error) {
                // Push provisioning may not be supported in desktop browsers
                if (result.error.code === "push_provisioning_not_available") {
                    this.state.status = "unsupported";
                } else {
                    this.state.status = "error";
                    this.state.errorMessage = result.error.message || "Wallet provisioning failed.";
                }
            } else {
                this.state.status = "success";
            }
        } catch (err) {
            console.error("Wallet provisioning error:", err);
            this.state.status = "error";
            this.state.errorMessage = err.message || "An unexpected error occurred.";
        }
    }

    goBack() {
        this.actionService.doAction({ type: "ir.actions.act_window_close" });
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// Shared helper
// ═══════════════════════════════════════════════════════════════════════════════

async function ensureStripeScript() {
    if (typeof Stripe !== "undefined") return;  // eslint-disable-line no-undef
    return new Promise((resolve, reject) => {
        const script = document.createElement("script");
        script.src = "https://js.stripe.com/v3/";
        script.onload = resolve;
        script.onerror = () => reject(new Error("Failed to load Stripe.js"));
        document.head.appendChild(script);
    });
}

// ═══════════════════════════════════════════════════════════════════════════════
// Register client actions
// ═══════════════════════════════════════════════════════════════════════════════

registry.category("actions").add("dojo_stripe_issuing_reveal", IssuingRevealAction);
registry.category("actions").add("dojo_stripe_issuing_wallet", IssuingWalletAction);
