# FarmProof Database Design

The proposed domain model contains 27 models:

1. User
2. FarmerProfile
3. Cooperative
4. CooperativeMembership
5. CooperativeStaffMembership
6. Farm
7. Plot
8. CropSeason
9. FarmActivity
10. InputRecord
11. ExpenseRecord
12. HarvestBatch
13. QualityInspection
14. InspectionPhoto
15. CoopIntake
16. StorageLocation
17. StockMovement
18. TransferRecord
19. TransferLine
20. LossRecord
21. SaleRecord
22. USSDSession
23. USSDRequestLog
24. IdempotencyRecord
25. HelpRequest
26. AuditEvent
27. RecordAmendment

These are proposed domain models, not yet implemented Django models.
Django authentication and framework tables will add further database tables.

All relationships, constraints and field definitions require review before implementation.
