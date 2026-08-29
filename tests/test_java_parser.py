"""Tests for JavaParser syntax and annotation extraction."""

import pytest
from collector.java_parser import JavaParser, parse_annotations
from collector.spring_extractor import SpringExtractor


def test_controller_endpoints_and_params():
    code = """package com.idfc.payments.controller;

import com.idfc.payments.dto.CreatePaymentRequest;
import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/v1/payments")
public class PaymentController {

    @GetMapping("/{id}")
    @PreAuthorize("hasRole('VIEWER')")
    public ResponseEntity<String> getPayment(
        @PathVariable("id") String paymentId,
        @RequestParam(name = "detail", required = false) boolean detail
    ) {
        return ResponseEntity.ok("payment-" + paymentId);
    }

    @PostMapping(
        value = "/create",
        consumes = "application/json"
    )
    public ResponseEntity<String> createPayment(@RequestBody @Valid CreatePaymentRequest request) {
        return ResponseEntity.ok("created");
    }
}
"""
    parser = JavaParser()
    parsed = parser.parse("PaymentController.java", code)
    extractor = SpringExtractor(parser)
    apis = extractor.extract_apis([parsed])

    assert len(apis) == 2

    get_ep = next(a for a in apis if a.http_method == "GET")
    assert get_ep.path == "/v1/payments/{id}"
    assert "id" in get_ep.path_variables or "paymentId" in get_ep.path_variables
    assert "detail" in get_ep.request_params
    assert "PreAuthorize" in get_ep.auth_annotations

    post_ep = next(a for a in apis if a.http_method == "POST")
    assert post_ep.path == "/v1/payments/create"
    assert post_ep.request_body_type == "CreatePaymentRequest"


def test_dto_validation_parsing():
    content = """package com.idfc.payments.dto;

import jakarta.validation.constraints.*;
import java.math.BigDecimal;

public class CreatePaymentRequest {
    @NotNull
    @Positive
    private BigDecimal amount;

    @NotBlank
    @Size(min = 2, max = 30, message = "Invalid customer ID")
    private String customerId;

    @Pattern(regexp = "^[A-Z]{3}$")
    private String currency;
}
"""
    parser = JavaParser()
    parsed = parser.parse("CreatePaymentRequest.java", content)
    cls = parsed.classes[0]
    assert len(cls.fields) == 3

    extractor = SpringExtractor(parser)
    rules = extractor.extract_validation_rules([parsed])
    assert len(rules) == 5  # NotNull, Positive, NotBlank, Size, Pattern


def test_pattern_annotation():
    text = '@Pattern(regexp = "^[A-Z]{3}$")\n    private String currency;'
    annos = parse_annotations(text)
    assert len(annos) == 1
    assert annos[0].name == "Pattern"
    assert annos[0].attributes.get("regexp") == "^[A-Z]{3}$"
    assert annos[0].raw_text == '@Pattern(regexp = "^[A-Z]{3}$")'
