-- Sample PT slabs (Maharashtra-style illustrative; verify against current law)
INSERT INTO pt_slabs (state, slab_min, slab_max, amount, effective_from, effective_to) VALUES
('Maharashtra', 0, 7500, 0, '2024-04-01', NULL),
('Maharashtra', 7500.01, 10000, 175, '2024-04-01', NULL),
('Maharashtra', 10000.01, 15000, 200, '2024-04-01', NULL),
('Maharashtra', 15000.01, 20000, 200, '2024-04-01', NULL),
('Maharashtra', 20000.01, 999999999, 300, '2024-04-01', NULL),
('Karnataka', 0, 15000, 0, '2024-04-01', NULL),
('Karnataka', 15000.01, 999999999, 200, '2024-04-01', NULL);

-- Sample LWF rates (illustrative)
INSERT INTO lwf_rates (state, wage_band_min, wage_band_max, employee_rate, employer_rate, effective_from, effective_to) VALUES
('Maharashtra', 0, 999999999, 10, 20, '2024-04-01', NULL),
('Karnataka', 0, 999999999, 3, 6, '2024-04-01', NULL);
