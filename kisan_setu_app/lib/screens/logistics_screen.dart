import 'package:flutter/material.dart';
import '../theme/app_colors.dart';
import '../theme/app_typography.dart';
import '../models/marketplace_model.dart';
import 'dart:convert';
import 'package:http/http.dart' as http;

class LogisticsScreen extends StatefulWidget {
  final bool isEmbeddedInNav;
  const LogisticsScreen({super.key, this.isEmbeddedInNav = false});

  @override
  State<LogisticsScreen> createState() => _LogisticsScreenState();
}

class _LogisticsScreenState extends State<LogisticsScreen> {
  List<MarketplaceOrder> orders = [];
  bool isLoading = true;

  @override
  void initState() {
    super.initState();
    _fetchOrders();
  }

  Future<void> _fetchOrders() async {
    try {
      final response = await http.get(Uri.parse('http://localhost:8000/api/v1/marketplace/orders?seller_id=PB-10492'));
      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        setState(() {
          orders = (data['orders'] as List)
              .map((item) => MarketplaceOrder.fromJson(item))
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
        title: const Text('Logistics & Orders'),
        backgroundColor: AppColors.primary,
        foregroundColor: AppColors.onPrimary,
      ),
      body: isLoading 
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _fetchOrders,
              child: ListView.builder(
                padding: const EdgeInsets.all(16),
                itemCount: orders.length,
                itemBuilder: (context, index) {
                  final order = orders[index];
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
                                'Order ${order.orderId}',
                                style: AppTypography.titleMedium(color: AppColors.primary),
                              ),
                              Container(
                                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                                decoration: BoxDecoration(
                                  color: AppColors.tertiaryContainer,
                                  borderRadius: BorderRadius.circular(20),
                                ),
                                child: Text(
                                  order.status,
                                  style: AppTypography.labelMedium(color: AppColors.onTertiaryContainer),
                                ),
                              ),
                            ],
                          ),
                          const SizedBox(height: 12),
                          Row(
                            children: [
                              const Icon(Icons.person, size: 20, color: AppColors.outline),
                              const SizedBox(width: 8),
                              Text('Buyer: ${order.buyerName}', style: AppTypography.bodyMedium(color: AppColors.onSurface)),
                            ],
                          ),
                          const SizedBox(height: 8),
                          Row(
                            children: [
                              const Icon(Icons.shopping_basket, size: 20, color: AppColors.outline),
                              const SizedBox(width: 8),
                              Text('${order.cropName} - ${order.quantityQuintals} Qtl', style: AppTypography.bodyMedium(color: AppColors.onSurface)),
                            ],
                          ),
                          const SizedBox(height: 12),
                          Row(
                            mainAxisAlignment: MainAxisAlignment.spaceBetween,
                            children: [
                              Text(
                                'Total: ₹${order.totalAmount}',
                                style: AppTypography.headlineSmall(color: AppColors.primary),
                              ),
                              ElevatedButton(
                                onPressed: () {},
                                style: ElevatedButton.styleFrom(
                                  backgroundColor: AppColors.primary,
                                  foregroundColor: AppColors.onPrimary,
                                ),
                                child: const Text('Route Map'),
                              ),
                            ],
                          )
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
