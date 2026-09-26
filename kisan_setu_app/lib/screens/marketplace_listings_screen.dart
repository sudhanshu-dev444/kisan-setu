import 'package:flutter/material.dart';
import '../theme/app_colors.dart';
import '../theme/app_typography.dart';
import '../models/marketplace_model.dart';
import 'dart:convert';
import 'package:http/http.dart' as http;

class MarketplaceListingsScreen extends StatefulWidget {
  final bool isEmbeddedInNav;
  const MarketplaceListingsScreen({super.key, this.isEmbeddedInNav = false});

  @override
  State<MarketplaceListingsScreen> createState() => _MarketplaceListingsScreenState();
}

class _MarketplaceListingsScreenState extends State<MarketplaceListingsScreen> {
  List<ProductListing> listings = [];
  bool isLoading = true;

  @override
  void initState() {
    super.initState();
    _fetchListings();
  }

  Future<void> _fetchListings() async {
    try {
      final response = await http.get(Uri.parse('http://localhost:8000/api/v1/marketplace/listings'));
      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        setState(() {
          listings = (data['listings'] as List)
              .map((item) => ProductListing.fromJson(item))
              .toList();
          isLoading = false;
        });
      } else {
        setState(() { isLoading = false; });
      }
    } catch (e) {
      setState(() { isLoading = false; });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.surface,
      appBar: widget.isEmbeddedInNav ? null : AppBar(
        title: const Text('My Listings'),
        backgroundColor: AppColors.primary,
        foregroundColor: AppColors.onPrimary,
      ),
      body: isLoading 
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _fetchListings,
              child: ListView.builder(
                padding: const EdgeInsets.all(16),
                itemCount: listings.length,
                itemBuilder: (context, index) {
                  final listing = listings[index];
                  return Card(
                    color: AppColors.surfaceBright,
                    margin: const EdgeInsets.only(bottom: 16),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(16),
                      side: const BorderSide(color: AppColors.outlineVariant, width: 2),
                    ),
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            mainAxisAlignment: MainAxisAlignment.spaceBetween,
                            children: [
                              Text(
                                listing.cropName,
                                style: AppTypography.headlineSmall(color: AppColors.primary),
                              ),
                              Container(
                                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                                decoration: BoxDecoration(
                                  color: AppColors.secondaryContainer,
                                  borderRadius: BorderRadius.circular(20),
                                ),
                                child: Text(
                                  listing.status,
                                  style: AppTypography.labelMedium(color: AppColors.onSecondaryContainer),
                                ),
                              ),
                            ],
                          ),
                          const SizedBox(height: 8),
                          Text(
                            '${listing.quantityQuintals} Quintals @ ₹${listing.pricePerQuintal}/Qtl',
                            style: AppTypography.titleMedium(color: AppColors.onSurface),
                          ),
                          const SizedBox(height: 8),
                          Text(
                            'Variety: ${listing.cropVariety ?? 'N/A'} • ${listing.locationVillage}, ${listing.locationDistrict}',
                            style: AppTypography.bodyMedium(color: AppColors.onSurfaceVariant),
                          ),
                        ],
                      ),
                    ),
                  );
                },
              ),
            ),
    );
  }
}
